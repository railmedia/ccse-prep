"""Text embeddings.

Local by default (fastembed/ONNX, no GPU, no per-token cost). The model name is
part of the storage key so several embedding models can coexist and be compared.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from functools import lru_cache
from typing import Any, Protocol

LOCAL_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
LOCAL_DIM = 384


class Embedder(Protocol):
    name: str
    dim: int

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class LocalEmbedder:
    """ONNX multilingual encoder served from the container."""

    name = LOCAL_MODEL
    dim = LOCAL_DIM

    def __init__(self) -> None:
        self._model: Any = None

    def _load(self) -> Any:
        if self._model is None:
            from fastembed import TextEmbedding

            self._model = TextEmbedding(model_name=self.name)
        return self._model

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        model = self._load()
        return [list(map(float, vector)) for vector in model.embed(list(texts))]


@lru_cache
def get_embedder(name: str = "local") -> Embedder:
    if name in {"local", LOCAL_MODEL}:
        return LocalEmbedder()
    raise ValueError(f"unknown embedder {name!r}")


async def embed_async(texts: Sequence[str], name: str = "local") -> list[list[float]]:
    """Embeddings are CPU-bound and synchronous: keep them off the event loop."""
    embedder = get_embedder(name)
    return await asyncio.to_thread(embedder.embed, texts)


def vector_literal(vector: Sequence[float]) -> str:
    return "[" + ",".join(f"{value:.6f}" for value in vector) + "]"
