# ADR 0004 — Thin HTTP adapters instead of vendor SDKs

**Status:** accepted · 2026-11-15

## Context

Mistral and OpenAI both publish official Python SDKs. Using them would be
idiomatic; writing adapters is more code.

## Decision

One `LLMProvider` protocol and small `httpx` adapters. The canonical request
carries a JSON schema, temperature, seed and role; adapters translate.

## Consequences

- The protocol is explicit and testable; adding a provider is ~50 lines.
- No SDK version coupling in the image, smaller dependency surface.
- We own retries, streaming parsing and JSON-mode differences — which is also
  the part worth demonstrating.
- Provider-specific features are not available until we add them deliberately.
