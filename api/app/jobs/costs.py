"""Render the LLM cost table from `llm_usage`."""

from __future__ import annotations

import asyncio
import sys
from decimal import Decimal

from sqlalchemy import func, select

from app.db import SessionLocal, dispose
from app.models import LlmUsage


async def run() -> None:
    async with SessionLocal() as session:
        rows = await session.execute(
            select(
                LlmUsage.kind,
                LlmUsage.provider,
                LlmUsage.model_id,
                func.count(),
                func.sum(LlmUsage.tokens_in),
                func.sum(LlmUsage.tokens_out),
                func.sum(LlmUsage.cost_eur),
                func.avg(LlmUsage.latency_ms),
            )
            .group_by(LlmUsage.kind, LlmUsage.provider, LlmUsage.model_id)
            .order_by(func.sum(LlmUsage.cost_eur).desc())
        )
        print("| kind | provider | model | calls | tokens in | tokens out | cost (€) | avg ms |")
        print("|---|---|---|---|---|---|---|---|")
        total = Decimal("0")
        for kind, provider, model, calls, tin, tout, cost, latency in rows:
            cost = cost or Decimal("0")
            total += cost
            print(
                f"| {kind} | {provider} | `{model}` | {calls} | {tin or 0} | {tout or 0} | "
                f"{cost:.4f} | {float(latency or 0):.0f} |"
            )
        print(f"\nTotal: **€{total:.4f}**")


async def _run() -> None:
    try:
        await run()
    finally:
        await dispose()


if __name__ == "__main__":
    asyncio.run(_run())
    sys.exit(0)
