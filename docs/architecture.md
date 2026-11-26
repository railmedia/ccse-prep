# Architecture

Four moving parts. Everything else is detail.

```
Astro (static)  ──►  FastAPI  ──►  Postgres 17 + pgvector
                        │
                        └──►  Mistral / OpenAI (LLM)   [optional; degradable]

              manual PDF ──► ingest job ──► questions + chunks
                                                │
                                          embed job ──► vectors
                                                │
                                        precompute job ──► explanations
```

## 1. Two data planes

| Plane | Content | Who may touch it | Determinism |
|---|---|---|---|
| A | 300 questions with the official key | exam engine only | exact |
| B | manual text, chunked and embedded | explanation layer only | retrieved, cited |

The exam engine never asks a model what the right answer is. Answers live in
Postgres and are applied server-side; the client never receives them before
submission. Generation can only explain.

This split is the core design decision: it keeps the exam faithful and
auditable while still allowing a generative layer where generation is useful.

## 2. Exam engine

- **Sampling** is stratified by task with fixed quotas (10/3/2/3/7). The bank's
  pools are exactly 12× those quotas, so campaign mode produces 12 disjoint
  exams covering all 300 questions (`app/exam/sampler.py`).
- **Scoring** happens on submit, from the database key, and writes one row per
  answer. That normalisation is what makes "most-failed questions" a query.
- **Timing** is server-authoritative (`started_at`), with the client rendering a
  countdown derived from `expires_at`. Late submissions are accepted but
  flagged (`expired`). Practice drills have no `expires_at`.
- **Feedback timing** is per exam: `end` (correct on submit, used by timed mocks
  and deferred drills) or `immediate` (practice only). Immediate feedback calls
  `POST /api/exams/{id}/check`, which verifies the exam belongs to the caller,
  that the question is in that exam, and that the exam opted in — otherwise it
  would be an answer oracle.

## 3. Retrieval and explanation

Ladder, each step measured (`docs/reports/scorecard.md`):

1. `dense` — multilingual MiniLM (ONNX, CPU, self-hosted)
2. `bm25` — Postgres `tsvector` in Spanish
3. `hybrid` — reciprocal-rank fusion
4. `hybrid+rerank` — lexical reranker (term overlap + phrase bonus)

Two constraints that matter more than the ranking function:

- **Hard task filter before retrieval.** A Task 1 question is never explained
  from Task 5 content.
- **The query includes the correct option** at generation time, because the
  explanation task is "justify this known answer", not "find the answer". The
  evaluation reports both query modes, since including the answer inflates
  lexical metrics.

Explanations are **precomputed** for all 300 questions by a batch job and stored
with citations, model id and retrieval config. The request path performs no
generation; only the tutor does.

Citations carry a page number and the nearest detected heading. Page numbers are
exact; section labels are heuristic (the PDF has no font metadata in the text
layer, so headings are inferred from length and capitalisation) and the UI shows
them only on hover for that reason.

## 4. Model layer

`app/llm` is a protocol plus thin HTTP adapters (Mistral, OpenAI, Ollama).
`models.yaml` maps roles (`explain`, `tutor`, `judge`) to ordered candidates.
Resolution skips providers without a key and providers whose circuit breaker is
open, so an outage degrades instead of failing.

When no provider is available, `app/rag/extractive.py` produces an explanation by
quoting the retrieved manual text. It cannot invent anything, and the UI labels
the model honestly.

## 5. Evaluation

`app/evals/run.py` measures recall@5 and MRR@10 against a golden set with
bootstrap CIs, in two query modes, plus cheap generation checks. Results are
written to `eval_runs` and rendered to `docs/reports/scorecard.md`; CI runs the
gate weekly.

The golden set's label rule is stated in `app/evals/build_golden.py` and is
deliberately mechanical (answer containment). It is objective and reproducible,
and it is **not** human judgement — the file says so, and the scorecard repeats
the caveat.

## 6. Operations

- One image per service, identical in dev/CI/prod; jobs reuse the API image.
- Traefik at the edge (existing), GHCR images tagged by commit SHA, deploy script
  with health-gated rollback.
- `/metrics` exposes request, LLM and quota counters in Prometheus text format.
- Cost is computed per call from `models.yaml` prices and stored in `llm_usage`.

## Deliberate omissions

| Not done | Why |
|---|---|
| ANN index (HNSW) | ~50 chunks: a sequential scan is microseconds; indexing would be noise |
| Celery/Redis | 300 rows of batch work does not need a queue |
| Cross-encoder reranker | ONNX cross-encoders add weight; the lexical reranker is measured and reported instead |
| User accounts | Anonymous ids keep attempts together without collecting identity |
| Local LLM in production | CPU inference cannot serve traffic, and Ollama has no auth |
