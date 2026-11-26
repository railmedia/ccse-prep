from __future__ import annotations

import json
import logging
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

logger = logging.getLogger(__name__)


class HttpChatProvider:
    """Shared behaviour for OpenAI-compatible chat completion endpoints."""

    name = "http"
    base_url = ""
    api_key = ""
    model = ""

    def available(self) -> bool:
        return bool(self.api_key and self.model)

    def _endpoint(self) -> str:
        raise NotImplementedError

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    def _payload(self, request: CompletionRequest, stream: bool) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": m.role, "content": m.content} for m in request.messages],
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "stream": stream,
        }
        if request.seed is not None:
            payload["random_seed"] = request.seed
        return payload

    def _parse(self, body: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
        raise NotImplementedError

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        timer = Timer()
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    self._endpoint(), headers=self._headers(), json=self._payload(request, False)
                )
        except httpx.HTTPError as error:
            raise ProviderError(f"{self.name}: {error}") from error

        if response.status_code >= 400:
            raise ProviderError(
                f"{self.name}: HTTP {response.status_code} {response.text[:200]}",
                retryable=response.status_code in {408, 409, 425, 429}
                or response.status_code >= 500,
            )

        text, model_id, usage = self._parse(response.json())
        tokens_in = int(usage.get("prompt_tokens") or estimate_tokens(str(request.messages)))
        tokens_out = int(usage.get("completion_tokens") or estimate_tokens(text))
        return CompletionResult(
            text=text,
            model_id=model_id,
            usage=Usage(tokens_in=tokens_in, tokens_out=tokens_out),
            cost_eur=Decimal("0"),
            latency_ms=timer.ms,
            provider=self.name,
        )

    async def stream(self, request: CompletionRequest) -> AsyncIterator[str]:
        payload = self._payload(request, True)
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream(
                "POST", self._endpoint(), headers=self._headers(), json=payload
            ) as response:
                if response.status_code >= 400:
                    detail = await response.aread()
                    raise ProviderError(
                        f"{self.name}: HTTP {response.status_code} {detail[:200]!r}"
                    )
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if not data or data == "[DONE]":
                        continue
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    delta = self._delta(chunk)
                    if delta:
                        yield delta

    def _delta(self, chunk: dict[str, Any]) -> str:
        raise NotImplementedError
