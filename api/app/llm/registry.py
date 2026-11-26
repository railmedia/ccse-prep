"""Model registry, routing and fallback.

Configuration lives in ``models.yaml``: adding a provider or a model is a data
change, not a code change.
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, replace
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from app.llm.base import CompletionRequest, CompletionResult, LLMProvider, ProviderError
from app.llm.providers.ollama import OllamaProvider
from app.llm.providers.openai_compatible import MistralProvider, OpenAIProvider
from app.metrics import metrics

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).with_name("models.yaml")

FAILURE_THRESHOLD = 5
COOLDOWN_SECONDS = 60


@dataclass(frozen=True)
class ModelSpec:
    alias: str
    provider: str
    model: str
    in_eur: Decimal
    out_eur: Decimal


@dataclass
class _ProviderState:
    failures: int = 0
    opened_at: float = 0.0

    @property
    def open(self) -> bool:
        if self.failures < FAILURE_THRESHOLD:
            return False
        return (time.monotonic() - self.opened_at) < COOLDOWN_SECONDS

    def record_failure(self) -> None:
        self.failures += 1
        if self.failures >= FAILURE_THRESHOLD:
            self.opened_at = time.monotonic()

    def record_success(self) -> None:
        self.failures = 0


def _money(value: Any) -> Decimal:
    return Decimal(str(value or 0))


class Registry:
    def __init__(self, path: Path = CONFIG_PATH) -> None:
        self._raw: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
        self._states: dict[str, _ProviderState] = {}

    # -- configuration -----------------------------------------------------
    @property
    def models(self) -> dict[str, ModelSpec]:
        out: dict[str, ModelSpec] = {}
        for alias, spec in (self._raw.get("models") or {}).items():
            out[alias] = ModelSpec(
                alias=alias,
                provider=str(spec["provider"]),
                model=str(spec.get("model", "")),
                in_eur=_money(spec.get("in_eur")),
                out_eur=_money(spec.get("out_eur")),
            )
        return out

    def _provider_config(self, name: str) -> dict[str, Any]:
        return dict((self._raw.get("providers") or {}).get(name) or {})

    # -- providers ---------------------------------------------------------
    def provider(self, name: str, model: str) -> LLMProvider | None:
        if name == "mistral":
            config = self._provider_config("mistral")
            return MistralProvider(
                base_url=str(config.get("base_url", "https://api.mistral.ai")),
                api_key=os.environ.get(str(config.get("api_key_env", "MISTRAL_API_KEY")), ""),
                model=model,
            )
        if name == "openai":
            config = self._provider_config("openai")
            return OpenAIProvider(
                base_url=str(config.get("base_url", "https://api.openai.com")),
                api_key=os.environ.get(str(config.get("api_key_env", "OPENAI_API_KEY")), ""),
                model=model,
            )
        if name == "ollama":
            config = self._provider_config("ollama")
            return OllamaProvider(
                base_url=str(config.get("base_url", "http://ollama:11434")),
                model=model,
                enabled=os.environ.get(
                    str(config.get("enabled_env", "LOCAL_LLM_ENABLED")), ""
                ).lower()
                in {"1", "true", "yes"},
            )
        return None

    def chain(self, role: str) -> list[ModelSpec]:
        models = self.models
        aliases = (self._raw.get("routes") or {}).get(role) or []
        return [models[alias] for alias in aliases if alias in models]

    def available_chain(self, role: str) -> list[ModelSpec]:
        return [spec for spec in self.chain(role) if self._is_available(spec)]

    def _is_available(self, spec: ModelSpec) -> bool:
        provider = self.provider(spec.provider, spec.model)
        if provider is None or not provider.available():
            return False
        return not self._state(spec.provider).open

    def _state(self, provider: str) -> _ProviderState:
        return self._states.setdefault(provider, _ProviderState())

    def has_llm(self, role: str) -> bool:
        return bool(self.available_chain(role))

    # -- calls -------------------------------------------------------------
    async def complete(self, role: str, request: CompletionRequest) -> CompletionResult:
        errors: list[str] = []
        candidates = self.available_chain(role)
        for attempt, spec in enumerate(candidates):
            provider = self.provider(spec.provider, spec.model)
            if provider is None:
                continue
            try:
                result = await provider.complete(request)
            except ProviderError as error:
                self._state(spec.provider).record_failure()
                metrics.inc("ccse_llm_fallbacks_total", provider=spec.provider, role=role)
                errors.append(f"{spec.alias}: {error}")
                logger.warning(
                    "llm.fallback",
                    extra={"provider": spec.provider, "model_id": spec.model, "env": role},
                )
                continue
            self._state(spec.provider).record_success()
            metrics.inc("ccse_llm_calls_total", provider=spec.provider, model=spec.alias, role=role)
            metrics.inc(
                "ccse_llm_tokens_total",
                result.usage.tokens_in,
                provider=spec.provider,
                kind="input",
            )
            metrics.inc(
                "ccse_llm_tokens_total",
                result.usage.tokens_out,
                provider=spec.provider,
                kind="output",
            )
            cost = (
                Decimal(result.usage.tokens_in) * spec.in_eur
                + Decimal(result.usage.tokens_out) * spec.out_eur
            ) / Decimal(1_000_000)
            metrics.observe("ccse_llm_cost_eur", float(cost), model=spec.alias)
            return replace(
                result,
                cost_eur=cost.quantize(Decimal("0.000001")),
                provider=spec.provider,
                fell_back=attempt > 0,
            )
        raise ProviderError("; ".join(errors) or f"no provider available for role {role!r}")

    async def stream(self, role: str, request: CompletionRequest) -> AsyncIterator[str]:
        for attempt, spec in enumerate(self.available_chain(role)):
            provider = self.provider(spec.provider, spec.model)
            if provider is None:
                continue
            produced = False
            try:
                async for delta in provider.stream(request):
                    produced = True
                    yield delta
                self._state(spec.provider).record_success()
                return
            except ProviderError as error:
                self._state(spec.provider).record_failure()
                logger.warning("llm.stream_fallback: %s", error)
                if produced:
                    # Restarting mid-answer would duplicate text; surface it.
                    raise
                if attempt + 1 >= len(self.available_chain(role)):
                    raise
        raise ProviderError(f"no provider available for role {role!r}")


@lru_cache
def registry() -> Registry:
    return Registry()


def provider_status() -> dict[str, bool]:
    reg = registry()
    status: dict[str, bool] = {}
    for alias, spec in reg.models.items():
        provider = reg.provider(spec.provider, spec.model)
        status[alias] = bool(provider and provider.available())
    return status
