from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import Question
from app.rag.store import explanation_payload

router = APIRouter(prefix="/api/questions", tags=["questions"])


@router.get("/{question_id}/explanation")
async def explanation(
    question_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    payload = await explanation_payload(session, question_id)
    if payload is not None:
        return payload

    if await session.get(Question, question_id) is None:
        raise HTTPException(status_code=404, detail="question not found")
    raise HTTPException(status_code=404, detail="no explanation precomputed for this question")
