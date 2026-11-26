"""Precompute explanations for every question.

Runs as a batch job, writes to Postgres, and is safe to re-run: the primary key
is (question, model, prompt_version, retrieval_cfg).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from app.db import SessionLocal, dispose
from app.llm.registry import registry
from app.models import Explanation, LlmUsage, Question
from app.rag.generate import DEFAULT_CFG, explain_question


async def run(
    *,
    cfg: str,
    limit: int | None,
    ids: list[str] | None,
    only_missing: bool,
) -> dict[str, Any]:
    stats: dict[str, Any] = {"generated": 0, "skipped": 0, "failed": 0, "cost_eur": 0.0}
    async with SessionLocal() as session:
        query = select(Question).order_by(Question.id)
        if ids:
            query = query.where(Question.id.in_(ids))
        questions = list((await session.execute(query)).scalars())
        if limit:
            questions = questions[:limit]

        for question in questions:
            if only_missing:
                existing = await session.scalar(
                    select(Explanation.question_id).where(
                        Explanation.question_id == question.id,
                        Explanation.retrieval_cfg == cfg,
                    )
                )
                if existing:
                    stats["skipped"] += 1
                    continue
            try:
                result = await explain_question(session, question, cfg=cfg)
            except Exception as error:  # one bad question must not stop the batch
                stats["failed"] += 1
                stats.setdefault("errors", []).append(f"{question.id}: {error}")
                # A failed statement poisons the transaction; reset it.
                await session.rollback()
                continue

            explanation = await session.scalar(
                select(Explanation).where(
                    Explanation.question_id == question.id,
                    Explanation.model == result.model,
                    Explanation.prompt_version == result.prompt_version,
                    Explanation.retrieval_cfg == cfg,
                )
            )
            values = {
                "model_id": result.model_id,
                "body_es": result.body["summary"] + "\n\n" + result.body["why_correct"],
                "payload": result.body,
                "citations": result.citations,
                "confidence": Decimal(str(round(result.confidence, 2))),
            }
            if explanation is None:
                session.add(
                    Explanation(
                        question_id=question.id,
                        model=result.model,
                        prompt_version=result.prompt_version,
                        retrieval_cfg=cfg,
                        status="draft",
                        **values,
                    )
                )
            else:
                for key, value in values.items():
                    setattr(explanation, key, value)

            if result.provider != "extractive":
                session.add(
                    LlmUsage(
                        kind="explain",
                        provider=result.provider,
                        model_id=result.model_id,
                        tokens_in=result.tokens_in,
                        tokens_out=result.tokens_out,
                        cost_eur=Decimal(str(result.cost_eur)),
                        latency_ms=0,
                    )
                )
                stats["cost_eur"] = float(stats["cost_eur"]) + result.cost_eur
            stats["generated"] += 1
            if stats["generated"] % 25 == 0:
                await session.commit()

        await session.commit()
    stats["provider_default"] = (
        "llm" if registry().has_llm("explain") else "extractive (no API key configured)"
    )
    stats["status"] = "ok"
    return stats


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    try:
        return await run(
            cfg=args.cfg, limit=args.limit, ids=args.ids, only_missing=args.only_missing
        )
    finally:
        await dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Precompute explanations")
    parser.add_argument("--cfg", default=DEFAULT_CFG)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--ids", default="", help="comma separated question ids")
    parser.add_argument("--only-missing", action="store_true")
    args = parser.parse_args(argv)
    args.ids = [value for value in args.ids.split(",") if value] or None
    result = asyncio.run(_run(args))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
