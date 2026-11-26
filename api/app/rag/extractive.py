"""Deterministic fallback explanations.

When no model is reachable (no API key, provider outage, offline development)
the app still explains every question by quoting the retrieved manual text.
It cannot be as good as a model, but it never invents anything, and the UI
labels it as extractive so nothing pretends otherwise.
"""

from __future__ import annotations

import re

from app.models import Question
from app.rag.search import RetrievedChunk, fold, tokens

MODEL = "extractive"
MODEL_ID = "extractive-v1"

_SENTENCE = re.compile(r"(?<=[.!?])\s+")


def _sentences(text: str) -> list[str]:
    return [sentence.strip() for sentence in _SENTENCE.split(text) if len(sentence.strip()) > 25]


def _best_sentence(chunks: list[RetrievedChunk], target: str) -> tuple[str, int, str]:
    """Return (sentence, page, chunk_id) for the most relevant sentence."""
    target_terms = tokens(target)
    best = ("", 0, "")
    best_score = -1.0
    for chunk in chunks:
        for sentence in _sentences(chunk.body):
            overlap = len(target_terms & tokens(sentence)) / (len(target_terms) or 1)
            if fold(target)[:60] in fold(sentence):
                overlap += 0.4
            if overlap > best_score:
                best, best_score = (sentence, chunk.page_from, chunk.id), overlap
    return best


def explain(question: Question, chunks: list[RetrievedChunk]) -> dict[str, object]:
    correct = next(
        (option["text"] for option in question.options if option["key"] == question.answer), ""
    )
    wrong = [option for option in question.options if option["key"] != question.answer]

    sentence, page, chunk_id = _best_sentence(chunks, f"{question.stem} {correct}")
    if sentence:
        why_correct = f"El manual lo explica así: «{sentence}» (pág. {page})."
    elif chunks:
        why_correct = f"El manual trata este punto en la página {chunks[0].page_from}."
    else:
        why_correct = "No se ha encontrado el punto correspondiente en el manual."

    why_others_wrong = [
        f"«{option['text']}» no coincide con lo que indica el manual "
        f"(pág. {chunks[0].page_from if chunks else '—'})."
        for option in wrong
    ]

    return {
        "summary": f"La respuesta correcta es «{correct}».",
        "why_correct": why_correct,
        "why_others_wrong": why_others_wrong,
        "used_chunks": ([chunk_id] if chunk_id else []) + [chunk.id for chunk in chunks[:1]],
        "confidence": 0.55 if sentence else 0.3,
    }
