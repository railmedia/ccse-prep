from __future__ import annotations

import json
from typing import Any

from app.llm.base import CompletionRequest
from app.llm.providers.http import HttpChatProvider


class MistralProvider(HttpChatProvider):
    name = "mistral"

    def __init__(self, *, base_url: str, api_key: str, model: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model

    def _endpoint(self) -> str:
        return f"{self.base_url}/v1/chat/completions"

    def _payload(self, request: CompletionRequest, stream: bool) -> dict[str, Any]:
        payload = super()._payload(request, stream)
        if request.json_schema is not None:
            # JSON mode plus the schema in the prompt: the most portable option
            # across Mistral model versions.
            payload["response_format"] = {"type": "json_object"}
        return payload

    def _parse(self, body: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
        choice = body["choices"][0]
        return (
            choice["message"].get("content") or "",
            body.get("model", self.model),
            body.get("usage") or {},
        )

    def _delta(self, chunk: dict[str, Any]) -> str:
        try:
            return chunk["choices"][0]["delta"].get("content") or ""
        except (KeyError, IndexError, TypeError):
            return ""


class OpenAIProvider(HttpChatProvider):
    name = "openai"

    def __init__(self, *, base_url: str, api_key: str, model: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model

    def _endpoint(self) -> str:
        return f"{self.base_url}/v1/chat/completions"

    def _payload(self, request: CompletionRequest, stream: bool) -> dict[str, Any]:
        payload = super()._payload(request, stream)
        payload.pop("random_seed", None)
        if request.seed is not None:
            payload["seed"] = request.seed
        if request.json_schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "explanation",
                    "strict": True,
                    "schema": request.json_schema,
                },
            }
        return payload

    def _parse(self, body: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
        choice = body["choices"][0]
        return (
            choice["message"].get("content") or "",
            body.get("model", self.model),
            body.get("usage") or {},
        )

    def _delta(self, chunk: dict[str, Any]) -> str:
        try:
            return chunk["choices"][0]["delta"].get("content") or ""
        except (KeyError, IndexError, TypeError):
            return ""


def parse_json_object(text: str) -> dict[str, Any] | None:
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            value = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None
    return value if isinstance(value, dict) else None
