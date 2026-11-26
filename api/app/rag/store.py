"""Read-side helpers shared by the question and exam routers."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Explanation, Question
from app.rag.search import TASK_LABELS


async def explanation_payload(session: AsyncSession, question_id: str) -> dict[str, Any] | None:
    """Latest precomputed explanation for a question, or None."""
    question = await session.get(Question, question_id)
    if question is None:
        return None

    row = await session.scalar(
        select(Explanation)
        .where(Explanation.question_id == question_id)
        .order_by(Explanation.created_at.desc())
        .limit(1)
    )
    if row is None:
        return None

    body = row.payload or {}
    return {
        "question_id": question.id,
        "task": question.task,
        "task_label": TASK_LABELS.get(question.task),
        "stem": question.stem,
        "options": question.options,
        "answer": question.answer,
        "summary": body.get("summary", ""),
        "why_correct": body.get("why_correct", ""),
        "why_others_wrong": body.get("why_others_wrong", []),
        "citations": row.citations,
        "confidence": float(row.confidence) if row.confidence is not None else None,
        "model": row.model,
        "model_id": row.model_id,
        "retrieval_cfg": row.retrieval_cfg,
        "status": row.status,
    }
