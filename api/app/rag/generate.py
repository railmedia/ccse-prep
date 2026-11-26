"""Explanation generation: retrieve, prompt, validate, fall back."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.base import CompletionRequest, ProviderError
from app.llm.providers.openai_compatible import parse_json_object
from app.llm.registry import registry
from app.models import Question
from app.rag import extractive
from app.rag.prompts import (
    EXPLAIN_PROMPT_VERSION,
    EXPLANATION_SCHEMA,
    build_query,
    explanation_messages,
)
from app.rag.search import TASK_LABELS, RetrievedChunk, search

logger = logging.getLogger(__name__)

DEFAULT_CFG = "hybrid+rerank"


@dataclass
class Explained:
    body: dict[str, Any]
    citations: list[dict[str, object]]
    model: str
    model_id: str
    prompt_version: str
    retrieval_cfg: str
    confidence: float
    tokens_in: int = 0
    tokens_out: int = 0
    cost_eur: float = 0.0
    provider: str = "extractive"


def _citations(payload: dict[str, Any], chunks: list[RetrievedChunk]) -> list[dict[str, object]]:
    by_id = {chunk.id: chunk for chunk in chunks}
    used = [str(chunk_id) for chunk_id in payload.get("used_chunks") or [] if chunk_id in by_id]
    if not used:
        used = [chunk.id for chunk in chunks[:2]]
    return [by_id[chunk_id].citation() for chunk_id in dict.fromkeys(used)][:3]


def _valid(payload: dict[str, Any] | None) -> bool:
    if not payload:
        return False
    return bool(payload.get("summary")) and bool(payload.get("why_correct"))


def _normalise(payload: dict[str, Any]) -> dict[str, Any]:
    wrong = payload.get("why_others_wrong") or []
    if not isinstance(wrong, list):
        wrong = [str(wrong)]
    try:
        confidence = min(1.0, max(0.0, float(payload.get("confidence", 0.5))))
    except (TypeError, ValueError):
        confidence = 0.5
    return {
        "summary": str(payload.get("summary", "")).strip(),
        "why_correct": str(payload.get("why_correct", "")).strip(),
        "why_others_wrong": [str(item) for item in wrong],
        "used_chunks": [str(item) for item in payload.get("used_chunks") or []],
        "confidence": confidence,
    }


async def explain_question(
    session: AsyncSession,
    question: Question,
    *,
    cfg: str = DEFAULT_CFG,
    k: int = 5,
) -> Explained:
    chunks = await search(session, build_query(question), question.task, cfg=cfg, k=k)

    if registry().has_llm("explain"):
        try:
            result = await registry().complete(
                "explain",
                CompletionRequest(
                    role="explain",
                    messages=explanation_messages(question, chunks),
                    json_schema=EXPLANATION_SCHEMA,
                    max_tokens=900,
                ),
            )
            payload = parse_json_object(result.text)
            if _valid(payload) and payload is not None:
                normalised = _normalise(payload)
                return Explained(
                    body=normalised,
                    citations=_citations(normalised, chunks),
                    model=_alias_for(result.model_id),
                    model_id=result.model_id,
                    prompt_version=EXPLAIN_PROMPT_VERSION,
                    retrieval_cfg=cfg,
                    confidence=float(str(normalised["confidence"])),
                    tokens_in=result.usage.tokens_in,
                    tokens_out=result.usage.tokens_out,
                    cost_eur=float(result.cost_eur),
                    provider=result.provider,
                )
            logger.warning(
                "explain.invalid_json",
                extra={"http_status": 200, "env": str(result.model_id)},
            )
        except ProviderError as error:
            logger.warning("explain.provider_error: %s", error)

    payload = extractive.explain(question, chunks)
    return Explained(
        body=payload,
        citations=_citations(payload, chunks),
        model=extractive.MODEL,
        model_id=extractive.MODEL_ID,
        prompt_version="none",
        retrieval_cfg=cfg,
        confidence=float(str(payload["confidence"])),
    )


def _alias_for(model_id: str) -> str:
    for alias, spec in registry().models.items():
        if spec.model == model_id:
            return alias
    return model_id


def question_context(question: Question) -> str:
    options = " | ".join(f"{option['key']}. {option['text']}" for option in question.options)
    return f"{question.stem} [{TASK_LABELS.get(question.task, '')}] opciones: {options}"


def as_text(body: dict[str, Any]) -> str:
    """Render an explanation body for plain-text consumers (tests, logs)."""
    parts = [body.get("summary", ""), body.get("why_correct", "")]
    parts.extend(body.get("why_others_wrong") or [])
    return "\n".join(part for part in parts if part)


def to_json(body: dict[str, Any]) -> str:
    return json.dumps(body, ensure_ascii=False)
