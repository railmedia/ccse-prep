# ADR 0005 — No ANN index, no job queue

**Status:** accepted · 2026-11-15

## Context

RAG deployments usually ship a vector index (HNSW/IVF) and a worker queue
(Celery/RQ) from day one. This corpus is 53 chunks and the batch jobs touch 300
rows.

## Decision

- Retrieve with exact search. Do not create a vector index.
- Batch jobs are one-shot containers of the API image; no broker, no worker.

## Consequences

- Fewer moving parts to operate, back up and explain.
- Recall is exact; "index tuning" cannot be blamed for a miss.
- Both choices must be revisited at scale: HNSW roughly above 10⁵ chunks, a
  queue when jobs need scheduling, retries or concurrency. The thresholds are
  written down so the decision can be re-evaluated rather than inherited.
