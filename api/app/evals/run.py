"""Golden-set evaluation.

Everything here is measured, not asserted: per-config retrieval quality with
bootstrap confidence intervals, plus cheap generation checks, written to
`eval_runs` and rendered as a markdown scorecard.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import statistics
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import func, select

from app.db import SessionLocal, dispose
from app.models import Chunk, EvalRun, Explanation, Question
from app.rag.prompts import build_query
from app.rag.search import fold, search

GOLDEN = Path(__file__).with_name("golden.yaml")
CONFIGS = ("dense", "bm25", "hybrid", "hybrid+rerank")
K = 5
BOOTSTRAP = 1000


@dataclass
class Item:
    question_id: str
    task: int
    chunk_id: str
    page: int
    section: str


@dataclass
class ConfigResult:
    cfg: str
    query_mode: str
    recall: float
    recall_ci: tuple[float, float]
    mrr: float
    mrr_ci: tuple[float, float]
    task_precision: float
    per_task: dict[int, float] = field(default_factory=dict)
    misses: list[str] = field(default_factory=list)


def load_golden() -> list[Item]:
    payload = yaml.safe_load(GOLDEN.read_text(encoding="utf-8"))
    return [
        Item(
            question_id=str(entry["question_id"]),
            task=int(entry["task"]),
            chunk_id=str(entry["chunk_id"]),
            page=int(entry.get("page", 0)),
            section=str(entry.get("section", "")),
        )
        for entry in payload["items"]
    ]


def _bootstrap(values: list[float], rng: random.Random) -> tuple[float, float]:
    if not values:
        return (0.0, 0.0)
    means = []
    for _ in range(BOOTSTRAP):
        sample = [rng.choice(values) for _ in values]
        means.append(statistics.fmean(sample))
    means.sort()
    low = means[int(0.025 * len(means))]
    high = means[int(0.975 * len(means)) - 1]
    return (round(low, 3), round(high, 3))


async def evaluate_config(
    session: Any,
    cfg: str,
    items: list[Item],
    questions: dict[str, Question],
    rng: random.Random,
    *,
    with_answer: bool,
) -> ConfigResult:
    hits: list[float] = []
    reciprocal: list[float] = []
    precision: list[float] = []
    per_task: dict[int, list[float]] = {}
    misses: list[str] = []

    for item in items:
        question = questions[item.question_id]
        query = build_query(question) if with_answer else question.stem
        results = await search(session, query, item.task, cfg=cfg, k=K)
        ids = [chunk.id for chunk in results]
        rank = ids.index(item.chunk_id) + 1 if item.chunk_id in ids else 0
        hits.append(1.0 if rank else 0.0)
        reciprocal.append(1.0 / rank if rank else 0.0)
        per_task.setdefault(item.task, []).append(1.0 if rank else 0.0)
        if results:
            precision.append(sum(1 for chunk in results if chunk.task == item.task) / len(results))
        if not rank:
            misses.append(item.question_id)

    return ConfigResult(
        cfg=cfg,
        query_mode="stem+answer" if with_answer else "stem only",
        recall=round(statistics.fmean(hits), 3) if hits else 0.0,
        recall_ci=_bootstrap(hits, rng),
        mrr=round(statistics.fmean(reciprocal), 3) if reciprocal else 0.0,
        mrr_ci=_bootstrap(reciprocal, rng),
        task_precision=round(statistics.fmean(precision), 3) if precision else 0.0,
        per_task={
            task: round(statistics.fmean(values), 3) for task, values in sorted(per_task.items())
        },
        misses=misses,
    )


async def generation_metrics(session: Any, items: list[Item]) -> dict[str, Any]:
    answers = {
        question.id: next(
            (option["text"] for option in question.options if option["key"] == question.answer), ""
        )
        for question in (await session.execute(select(Question))).scalars()
    }
    rows = list(
        (
            await session.execute(
                select(Explanation).where(
                    Explanation.question_id.in_([item.question_id for item in items])
                )
            )
        ).scalars()
    )
    if not rows:
        return {"items": 0}
    by_question = {row.question_id: row for row in rows}

    citation_hits = 0
    key_hits = 0
    coverage_hits = 0
    counted = 0
    for item in items:
        row = by_question.get(item.question_id)
        if row is None:
            continue
        counted += 1
        payload = row.payload or {}
        text = fold(
            " ".join(
                [
                    str(payload.get("summary", "")),
                    str(payload.get("why_correct", "")),
                    row.body_es,
                ]
            )
        )
        answer_text = fold(answers.get(item.question_id, ""))
        citations = {str(citation.get("chunk_id")) for citation in (row.citations or [])}
        citation_hits += 1 if item.chunk_id in citations else 0
        key_hits += 1 if answer_text and answer_text.strip(".") in text else 0
        wrong = payload.get("why_others_wrong") or []
        coverage_hits += 1 if len(wrong) >= 2 else 0

    return {
        "items": counted,
        "citation_precision": round(citation_hits / counted, 3) if counted else 0.0,
        "key_agreement": round(key_hits / counted, 3) if counted else 0.0,
        "distractor_coverage": round(coverage_hits / counted, 3) if counted else 0.0,
    }


def _git_sha() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def render(results: list[ConfigResult], generation: dict[str, Any], corpus: dict[int, int]) -> str:
    stamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    tasks = sorted({task for result in results for task in result.per_task})
    lines = [
        "# CCSE Prep — retrieval scorecard",
        "",
        f"Generated {stamp} · commit `{os.environ.get('GIT_SHA', _git_sha())}`",
        "",
        "Golden set: chunks containing the correct option verbatim (label rule in",
        "`app/evals/build_golden.py`). Recall@5 and MRR@10 with 95% bootstrap CIs.",
        "",
        "Two query modes are reported, because they measure different things:",
        "",
        "- **stem only** — find the section that justifies the question without knowing",
        "  the key. Leak-free, and the honest measure of retrieval quality.",
        "- **stem + answer** — what production uses when explaining a known question.",
        "  It rewards lexical matching against the answer, so expect inflated numbers.",
        "",
    ]
    for mode in ("stem only", "stem + answer"):
        subset = [result for result in results if result.query_mode == mode]
        if not subset:
            continue
        lines += [
            f"## Query mode: {mode}",
            "",
            "| config | recall@5 | 95% CI | MRR@10 | 95% CI | task precision |",
            "|---|---|---|---|---|---|",
        ]
        for result in subset:
            lines.append(
                f"| `{result.cfg}` | **{result.recall:.3f}** | "
                f"{result.recall_ci[0]:.3f}-{result.recall_ci[1]:.3f} | "
                f"{result.mrr:.3f} | {result.mrr_ci[0]:.3f}-{result.mrr_ci[1]:.3f} | "
                f"{result.task_precision:.3f} |"
            )
        lines += ["", "| config | " + " | ".join(f"T{task}" for task in tasks) + " |"]
        lines.append("|---|" + "---|" * len(tasks))
        for result in subset:
            cells = " | ".join(f"{result.per_task.get(task, 0):.2f}" for task in tasks)
            lines.append(f"| `{result.cfg}` | {cells} |")
        lines += [
            "",
            "Misses: "
            + "; ".join(
                f"`{result.cfg}` {', '.join(result.misses)}" for result in subset if result.misses
            )
            or "Misses: none",
            "",
        ]

    lines += [
        "Chance-level recall@5 (5 chunks requested from an N-chunk task pool): "
        + ", ".join(
            f"T{task} {min(1.0, K / max(1, size)):.2f}" for task, size in sorted(corpus.items())
        ),
        "— T2 is absent because true/false items cannot be labelled by containment, and",
        "T3's pool is small enough that its recall is weakly informative.",
        "",
        "## Generation checks",
        "",
    ]
    if generation.get("items"):
        lines += [
            f"Items: {generation['items']} · provider: {generation.get('provider', 'unknown')}",
            "",
            "| metric | value | meaning |",
            "|---|---|---|",
            "| citation_precision | "
            f"{generation['citation_precision']:.3f} | labelled chunk among citations |",
            "| key_agreement | "
            f"{generation['key_agreement']:.3f} | explanation states the official answer |",
            "| distractor_coverage | "
            f"{generation['distractor_coverage']:.3f} | all wrong options addressed |",
            "",
            "Generated by the extractive fallback, `key_agreement` is near-tautological",
            "(the template restates the key). It becomes meaningful once a model",
            "generates the explanations.",
        ]
    else:
        lines.append("No precomputed explanations found; run `make precompute`.")
    return "\n".join(lines) + "\n"


async def _run(configs: list[str]) -> dict[str, Any]:
    items = load_golden()
    rng = random.Random(20260)
    async with SessionLocal() as session:
        questions = {
            question.id: question
            for question in (await session.execute(select(Question))).scalars()
        }
        corpus = {
            int(task): int(count)
            for task, count in (
                await session.execute(select(Chunk.task, func.count()).group_by(Chunk.task))
            )
        }
        results = []
        for cfg in configs:
            for with_answer in (True, False):
                results.append(
                    await evaluate_config(
                        session, cfg, items, questions, rng, with_answer=with_answer
                    )
                )
        generation = await generation_metrics(session, items)

        session.add(
            EvalRun(
                git_sha=_git_sha(),
                config=",".join(configs),
                models=["extractive" if not generation.get("items") else "precomputed"],
                metrics={
                    "retrieval": [
                        {
                            "cfg": result.cfg,
                            "query_mode": result.query_mode,
                            "recall@5": result.recall,
                            "ci": result.recall_ci,
                            "mrr": result.mrr,
                            "per_task": result.per_task,
                        }
                        for result in results
                    ],
                    "generation": generation,
                    "items": len(items),
                },
            )
        )
        await session.commit()

        scorecard = render(results, generation, corpus)
        print(scorecard)
        production = next(
            (
                result
                for result in results
                if result.cfg == "hybrid+rerank" and result.query_mode == "stem only"
            ),
            None,
        )
        return {
            "items": len(items),
            "configs": configs,
            "production_recall": production.recall if production else None,
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the golden-set evaluation")
    parser.add_argument("--configs", default="dense,bm25,hybrid,hybrid+rerank")
    parser.add_argument(
        "--min-recall",
        type=float,
        default=None,
        help="exit non-zero if hybrid+rerank stem-only recall@5 is below this",
    )
    args = parser.parse_args(argv)
    configs = [cfg.strip() for cfg in args.configs.split(",") if cfg.strip()]
    unknown = [cfg for cfg in configs if cfg not in CONFIGS]
    if unknown:
        parser.error(f"unknown configs: {unknown}")
    if not GOLDEN.exists():
        parser.error(f"missing golden set: {GOLDEN}")

    async def runner() -> dict[str, Any]:
        try:
            return await _run(configs)
        finally:
            await dispose()

    summary = asyncio.run(runner())
    print(json.dumps({"status": "ok", **summary}, ensure_ascii=False), file=sys.stderr)
    if args.min_recall is not None:
        recall = summary.get("production_recall") or 0.0
        if recall < args.min_recall:
            print(
                f"eval gate failed: recall@5 {recall:.3f} < {args.min_recall:.3f}", file=sys.stderr
            )
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
