"""Provider-agnostic LLM interface.

Adapters are thin wrappers over HTTP so the protocol is explicit and the image
stays small. Nothing above this layer knows which vendor answered.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Protocol


class ProviderError(RuntimeError):
    """Transient or terminal provider failure; triggers fallback."""

    def __init__(self, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable


@dataclass(frozen=True)
class Message:
    role: str
    content: str


@dataclass(frozen=True)
class CompletionRequest:
    role: str
    messages: list[Message]
    json_schema: dict[str, Any] | None = None
    temperature: float = 0.0
    seed: int | None = 42
    max_tokens: int = 900


@dataclass(frozen=True)
class Usage:
    tokens_in: int = 0
    tokens_out: int = 0


@dataclass
class CompletionResult:
    text: str
    model_id: str
    usage: Usage
    cost_eur: Decimal
    latency_ms: int
    provider: str
    parsed: dict[str, Any] | None = None
    fell_back: bool = False
    raw: dict[str, Any] = field(default_factory=dict)


class LLMProvider(Protocol):
    name: str

    def available(self) -> bool: ...

    async def complete(self, request: CompletionRequest) -> CompletionResult: ...

    def stream(self, request: CompletionRequest) -> AsyncIterator[str]: ...


class Timer:
    """Small helper so every adapter reports latency the same way."""

    def __init__(self) -> None:
        self._start = time.perf_counter()

    @property
    def ms(self) -> int:
        return int((time.perf_counter() - self._start) * 1000)


def estimate_tokens(text: str) -> int:
    """Cheap approximation: good enough for cost accounting, not for billing."""
    return max(1, len(text) // 4)
