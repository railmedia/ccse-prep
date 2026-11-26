# ADR 0003 — Explanations are precomputed, only the tutor is live

**Status:** accepted · 2026-11-15

## Context

Every question needs a grounded explanation. Generating on request would make
latency and cost depend on a provider, and would make output unverifiable.

## Decision

A batch job generates all explanations, stores them with citations, model id,
prompt version and retrieval config. The API serves them from Postgres. Live
generation exists only for the free-form tutor, behind quotas.

## Consequences

- p50 latency for explanations is a database read (~ms), cost is zero at runtime.
- Outputs can be reviewed before publication and compared across models.
- A model change requires re-running the batch, which is deliberate and cheap.
- The dataset can drift from a newer manual until the batch is re-run; the
  `documents.sha256` and `source_year` make that visible.
