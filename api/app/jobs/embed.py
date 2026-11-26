"""Build chunk embeddings for one or more models."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any

from sqlalchemy import delete, select

from app.db import SessionLocal, dispose
from app.models import Chunk, ChunkEmbedding
from app.rag.embeddings import LOCAL_MODEL, embed_async, get_embedder

BATCH = 32


async def build(models: list[str], force: bool) -> dict[str, Any]:
    summary: dict[str, Any] = {"models": {}}
    async with SessionLocal() as session:
        rows = await session.execute(select(Chunk.id, Chunk.body).order_by(Chunk.id))
        chunks = list(rows)
        if not chunks:
            return {"status": "failed", "reason": "no chunks; run ingest first"}

        for model in models:
            embedder = get_embedder(model)
            name = embedder.name
            existing = await session.scalar(
                select(ChunkEmbedding.chunk_id).where(ChunkEmbedding.model == name).limit(1)
            )
            if existing is not None and not force:
                summary["models"][name] = {"status": "skipped", "reason": "already embedded"}
                continue

            await session.execute(delete(ChunkEmbedding).where(ChunkEmbedding.model == name))
            embedded = 0
            for start in range(0, len(chunks), BATCH):
                batch = chunks[start : start + BATCH]
                vectors = await embed_async([body for _, body in batch], model)
                for (chunk_id, _), vector in zip(batch, vectors, strict=True):
                    session.add(
                        ChunkEmbedding(
                            chunk_id=chunk_id, model=name, dim=len(vector), embedding=vector
                        )
                    )
                embedded += len(batch)
            summary["models"][name] = {"status": "ok", "chunks": embedded, "dim": embedder.dim}
        await session.commit()
    summary["status"] = "ok"
    return summary


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    try:
        return await build(args.models, force=args.force)
    finally:
        await dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build chunk embeddings")
    parser.add_argument("--models", default="local", help="'local' or a model name")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    names = [name.strip() for name in args.models.split(",") if name.strip()]
    args.models = [LOCAL_MODEL if name == "local" else name for name in names]
    result = asyncio.run(_run(args))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
