from __future__ import annotations

import json
import logging
import re
import uuid
from collections.abc import AsyncIterator
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import SessionLocal, get_session
from app.deps import current_anon
from app.llm.base import CompletionRequest, ProviderError
from app.llm.registry import registry
from app.metrics import metrics
from app.models import Quota
from app.rag.prompts import TUTOR_PROMPT_VERSION, tutor_messages
from app.rag.search import RetrievedChunk, search
from app.settings import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["tutor"])

DAILY_REQUESTS = 20
DAILY_TOKENS = 40_000
_SENTENCE = re.compile(r"(?<=[.!?])\s+")


class TutorIn(BaseModel):
    question: str = Field(min_length=3, max_length=500)
    task: int | None = Field(default=None, ge=1, le=5)


def _sse(event: str, payload: dict[str, object]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _extractive_answer(chunks: list[RetrievedChunk]) -> str:
    if not chunks:
        return "No encuentro ese contenido en el manual. Prueba a reformular la pregunta."
    top = chunks[0]
    sentences = [
        sentence.strip()
        for sentence in _SENTENCE.split(top.body)
        # Chunk overlap can start mid-sentence; skip fragments.
        if len(sentence.strip()) > 40 and sentence.strip()[:1].isupper()
    ]
    body = " ".join(sentences[:3]) or top.body[:280].strip()
    return f"{body}\n\n(Fuente: manual, página {top.page_from}.)"


async def _reserve_quota(session: AsyncSession, anon_id: uuid.UUID) -> None:
    today = date.today()
    row = await session.scalar(
        select(Quota).where(Quota.anon_id == anon_id, Quota.day == today).with_for_update()
    )
    if row is None:
        row = Quota(anon_id=anon_id, day=today, tutor_requests=0, tokens_used=0)
        session.add(row)
    if row.tutor_requests >= DAILY_REQUESTS or row.tokens_used >= DAILY_TOKENS:
        metrics.inc("ccse_quota_rejections_total", scope="tutor")
        raise HTTPException(status_code=429, detail="daily tutor quota exhausted")
    row.tutor_requests += 1
    await session.commit()


@router.post("/tutor")
async def tutor(
    payload: TutorIn,
    anon_id: uuid.UUID = Depends(current_anon),
    session: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    await _reserve_quota(session, anon_id)
    chunks = await search(session, payload.question, payload.task, cfg="hybrid+rerank", k=5)
    use_llm = registry().has_llm("tutor")
    model = "extractive" if not use_llm else "route"
    citations = [chunk.citation() for chunk in chunks[:3]]

    async def events() -> AsyncIterator[str]:
        try:
            if use_llm:
                request = CompletionRequest(
                    role="tutor",
                    messages=tutor_messages(payload.question, chunks),
                    max_tokens=600,
                )
                async for delta in registry().stream("tutor", request):
                    yield _sse("delta", {"delta": delta})
            else:
                for word in _extractive_answer(chunks).split(" "):
                    yield _sse("delta", {"delta": word + " "})
        except ProviderError as error:
            logger.warning("tutor.provider_error: %s", error)
            yield _sse("error", {"detail": "el modelo no está disponible; prueba más tarde"})
            return
        finally:
            await _record_usage(anon_id)
        yield _sse(
            "done",
            {
                "citations": citations,
                "model": model,
                "prompt_version": TUTOR_PROMPT_VERSION,
            },
        )

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


async def _record_usage(anon_id: uuid.UUID) -> None:
    """Best-effort accounting in a fresh session (the request one is closed)."""
    try:
        async with SessionLocal() as session:
            today = date.today()
            row = await session.scalar(
                select(Quota).where(Quota.anon_id == anon_id, Quota.day == today)
            )
            if row is not None:
                row.tokens_used += 300
                await session.commit()
    except Exception:
        logger.debug("tutor.usage_not_recorded", exc_info=True)


@router.get("/tutor/config")
async def tutor_config() -> dict[str, object]:
    return {
        "llm_available": registry().has_llm("tutor"),
        "daily_requests": DAILY_REQUESTS,
        "env": settings.env,
    }
