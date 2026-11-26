from __future__ import annotations

import pytest_asyncio
from sqlalchemy import func, select

from app.db import SessionLocal
from app.models import Question

# Minimum pool per task to satisfy sampler.QUOTA (10/3/2/3/7).
_TASK_QUOTAS = {1: 10, 2: 3, 3: 2, 4: 3, 5: 7}


def _synthetic(task: int, index: int) -> Question:
    return Question(
        id=f"{task}{index:03d}",
        task=task,
        kind="mc",
        stem=f"Pregunta sintética {task}{index:03d}",
        options=[{"key": key, "text": f"opción {key}"} for key in "abc"],
        answer="a",
        source_page=1,
        source_year=2026,
    )


@pytest_asyncio.fixture(scope="session")
async def seeded_bank() -> None:
    """A minimal bank so integration tests can run against an empty database.

    CI starts with no questions (the manual is ingested only by the weekly eval
    job and by `infra/bootstrap.sh`). Tests that create exams need at least one
    quota per task. When a real bank is present — local development — this is a
    no-op.
    """
    async with SessionLocal() as session:
        total = await session.scalar(select(func.count()).select_from(Question))
        if total:
            return
        for task, quota in _TASK_QUOTAS.items():
            for index in range(1, quota + 1):
                session.add(_synthetic(task, index))
        await session.commit()
