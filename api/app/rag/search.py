"""Retrieval: lexical, dense, fusion and a lexical reranker.

The ladder exists so the evaluation can prove each step is worth its cost:

    dense → bm25 → hybrid (RRF) → hybrid+rerank

At this corpus size (~50 chunks) every query is a sequential scan, which is
faster than an ANN index and simpler to reason about.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.rag.embeddings import LOCAL_MODEL, embed_async, vector_literal

RRF_K = 60
_WORD = re.compile(r"[a-z0-9áéíóúüñ]+")

TASK_LABELS = {
    1: "Gobierno, legislación y participación ciudadana",
    2: "Derechos y deberes fundamentales",
    3: "Organización territorial y geografía",
    4: "Cultura e historia de España",
    5: "Sociedad española y vida cotidiana",
}


def fold(text: str) -> str:
    """Lowercase and strip accents, for lexical comparisons only."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def tokens(text: str) -> set[str]:
    return {token for token in _WORD.findall(fold(text)) if len(token) > 2}


@dataclass
class RetrievedChunk:
    id: str
    body: str
    section_path: list[str]
    page_from: int
    page_to: int
    task: int = 0
    score: float = 0.0
    sources: list[str] = field(default_factory=list)

    def citation(self) -> dict[str, object]:
        return {
            "chunk_id": self.id,
            "page": self.page_from,
            "section": " > ".join(self.section_path),
        }


_COLUMNS = "c.id, c.body, c.section_path, c.page_from, c.page_to, c.task"

_BM25_SQL = text(
    f"""
    SELECT {_COLUMNS},
           ts_rank_cd(c.tsv, websearch_to_tsquery('spanish', :query)) AS score
    FROM chunks c
    WHERE (CAST(:task AS smallint) IS NULL OR c.task = CAST(:task AS smallint))
      AND c.tsv @@ websearch_to_tsquery('spanish', :query)
    ORDER BY score DESC
    LIMIT :limit
    """
)

_DENSE_SQL = text(
    f"""
    SELECT {_COLUMNS},
           1 - (ce.embedding <=> CAST(:vector AS vector)) AS score
    FROM chunk_embeddings ce
    JOIN chunks c ON c.id = ce.chunk_id
    WHERE ce.model = :model
      AND (CAST(:task AS smallint) IS NULL OR c.task = CAST(:task AS smallint))
    ORDER BY ce.embedding <=> CAST(:vector AS vector)
    LIMIT :limit
    """
)


def _row_to_chunk(row, source: str) -> RetrievedChunk:  # type: ignore[no-untyped-def]
    return RetrievedChunk(
        id=row[0],
        body=row[1],
        section_path=list(row[2]),
        page_from=row[3],
        page_to=row[4],
        task=int(row[5]),
        score=float(row[6] or 0.0),
        sources=[source],
    )


async def _bm25(
    session: AsyncSession, query: str, task: int | None, limit: int
) -> list[RetrievedChunk]:
    if not tokens(query):
        return []
    rows = await session.execute(_BM25_SQL, {"query": query, "task": task, "limit": limit})
    return [_row_to_chunk(row, "bm25") for row in rows]


async def _dense(
    session: AsyncSession, query: str, task: int | None, limit: int, model: str = LOCAL_MODEL
) -> list[RetrievedChunk]:
    vectors = await embed_async([query])
    rows = await session.execute(
        _DENSE_SQL,
        {"vector": vector_literal(vectors[0]), "model": model, "task": task, "limit": limit},
    )
    return [_row_to_chunk(row, "dense") for row in rows]


def _rrf(results: list[list[RetrievedChunk]], k: int = RRF_K) -> list[RetrievedChunk]:
    merged: dict[str, RetrievedChunk] = {}
    scores: dict[str, float] = {}
    for ranking in results:
        for rank, chunk in enumerate(ranking, start=1):
            scores[chunk.id] = scores.get(chunk.id, 0.0) + 1.0 / (k + rank)
            if chunk.id in merged:
                merged[chunk.id].sources = sorted(set(merged[chunk.id].sources) | {*chunk.sources})
            else:
                merged[chunk.id] = chunk
    for chunk_id, chunk in merged.items():
        chunk.score = scores[chunk_id]
    return sorted(merged.values(), key=lambda chunk: chunk.score, reverse=True)


def rerank(
    query: str, chunks: list[RetrievedChunk], query_terms: set[str], top_k: int
) -> list[RetrievedChunk]:
    """Lexical reranker: term overlap plus phrase bonus.

    A cross-encoder would be stronger; this stays CPU-cheap and dependency-free,
    and the eval reports the difference honestly.
    """
    for chunk in chunks:
        chunk_terms = tokens(chunk.body)
        overlap = len(query_terms & chunk_terms) / (len(query_terms) or 1)
        phrase = 0.15 if fold(query)[:80] in fold(chunk.body) else 0.0
        chunk.score = 0.55 * overlap + 0.30 * chunk.score + phrase
    return sorted(chunks, key=lambda chunk: chunk.score, reverse=True)[:top_k]


async def search(
    session: AsyncSession,
    query: str,
    task: int | None,
    *,
    cfg: str = "hybrid+rerank",
    k: int = 5,
    candidates: int = 20,
    dense_model: str = LOCAL_MODEL,
) -> list[RetrievedChunk]:
    """Retrieve chunks for a question. ``task`` is a hard filter, always."""
    lexical: list[RetrievedChunk] = []
    dense: list[RetrievedChunk] = []

    if cfg in {"bm25", "hybrid", "hybrid+rerank"}:
        lexical = await _bm25(session, query, task, candidates)
    if cfg in {"dense", "hybrid", "hybrid+rerank"}:
        dense = await _dense(session, query, task, candidates, model=dense_model)

    if cfg == "bm25":
        return lexical[:k]
    if cfg == "dense":
        return dense[:k]

    fused = _rrf([ranking for ranking in (lexical, dense) if ranking])
    if cfg == "hybrid":
        return fused[:k]
    if cfg == "hybrid+rerank":
        return rerank(query, fused[:candidates], tokens(query), k)
    raise ValueError(f"unknown retrieval config {cfg!r}")
