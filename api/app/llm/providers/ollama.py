"""Ollama adapter — developer machines only.

Never enabled in production: CPU inference cannot serve traffic and the
endpoint is unauthenticated.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Any

import httpx

from app.llm.base import (
    CompletionRequest,
    CompletionResult,
    ProviderError,
    Timer,
    Usage,
    estimate_tokens,
)


class OllamaProvider:
    name = "ollama"

    def __init__(self, *, base_url: str, model: str, enabled: bool = False) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.enabled = enabled

    def available(self) -> bool:
        # Local inference is opt-in: it is a developer-machine feature and must
        # never be picked up silently in production.
        return self.enabled and bool(self.model)

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        timer = Timer()
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": m.role, "content": m.content} for m in request.messages],
            "stream": False,
            "options": {"temperature": request.temperature, "seed": request.seed},
        }
        if request.json_schema is not None:
            payload["format"] = "json"
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(f"{self.base_url}/api/chat", json=payload)
                response.raise_for_status()
                body = response.json()
        except httpx.HTTPError as error:
            raise ProviderError(f"ollama: {error}") from error

        text = str(body.get("message", {}).get("content", ""))
        return CompletionResult(
            text=text,
            model_id=str(body.get("model", self.model)),
            usage=Usage(
                tokens_in=int(body.get("prompt_eval_count") or estimate_tokens(text)),
                tokens_out=int(body.get("eval_count") or estimate_tokens(text)),
            ),
            cost_eur=Decimal("0"),
            latency_ms=timer.ms,
            provider=self.name,
        )

    async def stream(self, request: CompletionRequest) -> AsyncIterator[str]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": m.role, "content": m.content} for m in request.messages],
            "stream": True,
        }
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream("POST", f"{self.base_url}/api/chat", json=payload) as response:
                if response.status_code >= 400:
                    raise ProviderError(f"ollama: HTTP {response.status_code}")
                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    content = chunk.get("message", {}).get("content")
                    if content:
                        yield str(content)
