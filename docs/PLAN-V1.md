# CCSE Prep — Plan v1

**Status:** implemented (v1) — see §21 for what actually shipped
**Scope:** v1 (public demo at `ccse-prep.tudorache.me`)
**Owner:** Adrian Tudorache
**Last updated:** 2026-11-15

---

## 1. Purpose

A study application for the Spanish **CCSE** exam (*Conocimientos Constitucionales y Socioculturales de España*), the civics test required for Spanish nationality. Students sit full 25-question mock exams drawn from the official question bank, then receive an explanation for every question grounded in the official preparation manual, with page citations.

The application is also a **portfolio artefact** for a move from 16 years of PHP/WordPress development into AI engineering and DevOps. It is therefore designed to demonstrate three things to a hiring panel:

1. retrieval engineering with defensible, documented design choices;
2. measurement — a golden set, an eval harness, published scores, CI gates;
3. operations — reproducible containers, deploy pipeline, tracing, cost control.

**Anti-goal:** a chatbot demo. If a component can be made deterministic, it is made deterministic.

---

## 2. Goals and non-goals

### Goals

| # | Goal |
|---|---|
| G1 | Parse the official 2026 manual into 300 validated questions plus a section-aware corpus. |
| G2 | Run exam-faithful mock exams: 25 questions, 45 minutes, 3 options (2 for true/false), 15/25 to pass, no negative marking. |
| G3 | Generate a grounded, cited explanation for every one of the 300 questions, precomputed and versioned. |
| G4 | Provide a free-form tutor over the manual, rate-limited and cost-capped. |
| G5 | Measure retrieval and generation quality with a golden set, published as a scorecard. |
| G6 | Run identically in development, CI and production, as containers. |
| G7 | Support at least two LLM providers (Mistral, OpenAI) behind one interface, with measured comparison. |

### Non-goals (v1)

- User accounts, social features, leaderboards, monetisation.
- Generating new questions with an LLM (exam fidelity and hallucination risk are not worth it).
- Offline/PWA mode (revisit after v1).
- Native mobile apps.
- Multi-language UI. Explanations are Spanish; a translation layer is a later, separately evaluated feature.

---

## 3. Domain reference

Verified against the 2026 manual and the Instituto Cervantes exam specification.

### Exam format

| Property | Value |
|---|---|
| Questions | 25 |
| Duration | 45 minutes |
| Options | 3 (multiple choice); 2 (true/false) |
| Pass mark | 15/25 (60%) |
| Penalty | none for wrong or blank answers |
| Result | APTO / NO APTO |
| Certificate validity | does not expire |

### Task structure (exam blueprint)

| Task | Content | Questions | Block |
|---|---|---|---|
| 1 | Government, state powers and institutions, fundamental laws, citizen participation | 10 | Part 1 — 60% |
| 2 | Duties and rights attached to Spanish nationality (true/false) | 3 | Part 1 |
| 3 | Territorial organisation, physical and political geography | 2 | Part 1 |
| 4 | Traditions, culture, relevant historical events | 3 | Part 2 — 40% |
| 5 | Everyday life, social behaviour, administrative procedures | 7 | Part 2 |

### Question bank inventory (verified from the 2026 PDF)

| Task | ID range | Count | Exam quota | Ratio |
|---|---|---|---|---|
| 1 | 1001–1120 | 120 | 10 | 1/12 |
| 2 | 2001–2036 | 36 | 3 | 1/12 |
| 3 | 3001–3024 | 24 | 2 | 1/12 |
| 4 | 4001–4036 | 36 | 3 | 1/12 |
| 5 | 5001–5084 | 84 | 7 | 1/12 |
| **Total** | | **300** | **25** | |

**Key structural fact:** every pool is exactly 12× its exam quota. The bank therefore divides into **12 disjoint, blueprint-faithful mock exams** covering all 300 questions exactly once. This drives the sampling design (§10).

### Manual layout

- 102 pages, A4, produced in InDesign; text layer present (no OCR needed).
- Part 1: content chapters per task, with numbered figures and captions, plus per-section glossaries.
- Part 2: `PREGUNTAS` blocks per task, two-column layout.
- Part 3: `SOLUCIONES` table (pages 99–101), five columns per task block.

---

## 4. Source data and legal

The manual is © Instituto Cervantes and distributed free of charge for candidate preparation. Free download does not equal free redistribution.

**Policy for v1:**

- Repository commits **10 sample questions** and the ingestion pipeline only.
- Full bank and corpus live in Postgres on the VPS, never in git, never in Docker image layers.
- No bulk export endpoint; `/api` sends `X-Robots-Tag: noindex`.
- Attribution in the footer and README; explicit "not affiliated with the Instituto Cervantes" notice.
- Non-commercial, no advertising, no paywall.
- Ingestion is idempotent and keyed on the PDF's SHA-256, so a 2027 manual can be re-ingested without code changes.

If asked to take it down, the answer is a single `docker compose down` — worth stating because it shows the decision was deliberate.

---

## 5. Architecture

### Two data planes

```
                ┌─────────────────────────────────────────┐
                │  Plane A — structured, deterministic    │
                │  questions (300, validated, no LLM)     │
                └───────────────┬─────────────────────────┘
                                │  exam engine (sampling, scoring)
                                ▼
   Astro (static)  ◄──────►  FastAPI  ◄──────►  Postgres 17 + pgvector
                                ▲
                                │  explanation API (retrieval + generation)
                ┌───────────────┴─────────────────────────┐
                │  Plane B — unstructured, retrieved      │
                │  manual corpus (section chunks, cited)  │
                └─────────────────────────────────────────┘
```

The exam engine never consults Plane B for correctness. The key lives in the database and is applied server-side. Generation only ever explains; it cannot choose questions or determine answers.

### Request paths

| Path | Data | LLM | Latency target |
|---|---|---|---|
| Start exam | questions, no answers | none | <100 ms |
| Submit exam | deterministic scoring | none | <150 ms |
| Explanation | precomputed, cached | none (build time) | <80 ms |
| Tutor | retrieval + generation | live, streamed | first token <1.5 s |

---

## 6. Repository layout

```
ccse-prep/
├── api/
│   ├── app/
│   │   ├── main.py
│   │   ├── settings.py              # pydantic-settings
│   │   ├── routers/                 # exams, questions, tutor, admin, health
│   │   ├── models/                  # SQLAlchemy 2.0, typed
│   │   ├── schemas/                 # pydantic v2 DTOs
│   │   ├── ingest/                  # pdf.py questions.py solutions.py chunks.py
│   │   ├── rag/                     # search.py rerank.py query.py generate.py prompts/
│   │   ├── llm/                     # base.py registry.py providers/{mistral,openai,local}.py
│   │   ├── jobs/                    # ingest.py build_index.py precompute.py
│   │   └── evals/                   # harness, judges, scorecard renderer
│   ├── migrations/                  # alembic
│   ├── tests/
│   │   ├── unit/                    # cassette-backed, no network
│   │   ├── integration/             # -m local, -m remote
│   │   └── cassettes/
│   ├── pyproject.toml               # uv, ruff, mypy, pytest
│   └── Dockerfile
├── web/                             # Astro + React islands
├── data/
│   ├── questions.sample.json        # 10 questions, committed
│   └── manual/                      # gitignored
├── evals/golden/questions.yaml      # golden set + labels
├── infra/
│   ├── compose.yml                  # shared service definitions
│   ├── compose.dev.yml
│   ├── compose.prod.yml
│   ├── compose.local-gpu.yml
│   ├── traefik.dynamic.yml
│   ├── nginx.conf
│   └── deploy.sh
├── docs/
│   ├── PLAN-V1.md                   # this document
│   ├── architecture.md
│   ├── adr/                         # short decision records
│   └── reports/                     # generated scorecards, Pareto plot
├── Makefile
└── .github/workflows/ci.yml
```

A single root `Makefile` is the only interface a reviewer needs: `make up`, `make ingest`, `make eval`, `make scorecard`, `make deploy`.

---

## 7. Data model

Postgres 17 with `pgvector`.

```sql
CREATE EXTENSION IF NOT EXISTS vector;

-- Provenance ---------------------------------------------------------------
CREATE TABLE documents (
    id            uuid PRIMARY KEY,
    source_year   smallint     NOT NULL,          -- 2026
    filename      text         NOT NULL,
    sha256        text         NOT NULL UNIQUE,   -- idempotent ingestion
    pages         smallint     NOT NULL,
    ingested_at   timestamptz  NOT NULL DEFAULT now()
);

-- Retrieval corpus ---------------------------------------------------------
CREATE TABLE chunks (
    id            text PRIMARY KEY,               -- 't1/cortes-generales/03'
    document_id   uuid NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    task          smallint NOT NULL CHECK (task BETWEEN 1 AND 5),
    section_path  text[]   NOT NULL,              -- {'Tarea 1','Las Cortes Generales'}
    page_from     smallint NOT NULL,
    page_to       smallint NOT NULL,
    body          text     NOT NULL,
    token_count   smallint NOT NULL,
    tsv           tsvector GENERATED ALWAYS AS (to_tsvector('spanish', body)) STORED
);
CREATE INDEX chunks_tsv_idx ON chunks USING gin (tsv);
CREATE INDEX chunks_task_idx ON chunks (task);

-- One row per embedding model, so models can be compared -------------------
CREATE TABLE chunk_embeddings (
    chunk_id      text   NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
    model         text   NOT NULL,                -- 'bge-m3', 'text-embedding-3-small'
    dim           smallint NOT NULL,
    embedding     vector NOT NULL,
    PRIMARY KEY (chunk_id, model)
);

-- Question bank ------------------------------------------------------------
CREATE TABLE questions (
    id            text PRIMARY KEY,               -- '1016'
    task          smallint NOT NULL,
    kind          text NOT NULL CHECK (kind IN ('mc','vf')),
    stem          text NOT NULL,
    options       jsonb NOT NULL,                 -- [{"key":"a","text":"..."}, ...]
    answer        char(1) NOT NULL,               -- never serialised to clients
    source_page   smallint NOT NULL,
    source_year   smallint NOT NULL,
    notes         text                            -- parser flags, source typos
);

-- Exam sessions ------------------------------------------------------------
CREATE TABLE anon_users (
    id            uuid PRIMARY KEY,
    created_at    timestamptz NOT NULL DEFAULT now(),
    last_seen_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE exam_sessions (
    id             uuid PRIMARY KEY,
    anon_id        uuid NOT NULL REFERENCES anon_users(id),
    mode           text NOT NULL CHECK (mode IN ('campaign','random','practice')),
    campaign_slot  smallint,                      -- 1..12 for campaign mode
    question_ids   text[] NOT NULL,
    started_at     timestamptz NOT NULL DEFAULT now(),
    submitted_at   timestamptz,
    score          smallint,
    task_breakdown jsonb,
    duration_s     integer
);

CREATE TABLE exam_answers (
    exam_id       uuid NOT NULL REFERENCES exam_sessions(id) ON DELETE CASCADE,
    question_id   text NOT NULL REFERENCES questions(id),
    selected      char(1),                        -- NULL = blank
    is_correct    boolean NOT NULL,
    PRIMARY KEY (exam_id, question_id)
);
CREATE INDEX exam_answers_question_idx ON exam_answers (question_id);

-- Explanations, versioned by model and config ------------------------------
CREATE TABLE explanations (
    question_id    text NOT NULL REFERENCES questions(id),
    model          text NOT NULL,                 -- registry alias
    model_id       text NOT NULL,                 -- exact version from provider
    prompt_version text NOT NULL,
    retrieval_cfg  text NOT NULL,                 -- 'hybrid+rerank@v2'
    body_es        text NOT NULL,
    citations      jsonb NOT NULL,                -- [{chunk_id,page,section}]
    confidence     numeric(3,2),
    status         text NOT NULL DEFAULT 'draft'
                   CHECK (status IN ('draft','reviewed','rejected')),
    created_at     timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (question_id, model, prompt_version, retrieval_cfg)
);

-- Evaluation and cost ------------------------------------------------------
CREATE TABLE eval_runs (
    id          uuid PRIMARY KEY,
    git_sha     text NOT NULL,
    config      text NOT NULL,
    models      text[] NOT NULL,
    metrics     jsonb NOT NULL,
    cost_eur    numeric(8,4),
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE llm_usage (
    id          bigserial PRIMARY KEY,
    kind        text NOT NULL,                    -- explain|tutor|judge
    provider    text NOT NULL,
    model_id    text NOT NULL,
    tokens_in   integer NOT NULL,
    tokens_out  integer NOT NULL,
    cost_eur    numeric(8,4) NOT NULL,
    latency_ms  integer NOT NULL,
    fell_back   boolean NOT NULL DEFAULT false,
    created_at  timestamptz NOT NULL DEFAULT now()
);

-- Cost control -------------------------------------------------------------
CREATE TABLE quota (
    anon_id         uuid NOT NULL REFERENCES anon_users(id),
    day             date NOT NULL,
    tutor_requests  smallint NOT NULL DEFAULT 0,
    tokens_used     integer NOT NULL DEFAULT 0,
    PRIMARY KEY (anon_id, day)
);
```

Design notes:

- `exam_answers` is normalised, which makes per-question difficulty ("the 20 most-failed questions") a query rather than a feature request.
- `explanations` is keyed by `(question_id, model, prompt_version, retrieval_cfg)` so configs are compared over identical questions.
- No ANN index on `embedding`: at ~300 chunks a sequential scan is microseconds, and the README says why (`HNSW is unjustified below ~10⁵ chunks`). Revisit if the corpus grows to other manuals.
- `quota` enforces cost in the application; Traefik's rate limiter only handles abuse. Two different jobs.

---

## 8. Ingestion

### Pipeline

```
PDF ──► documents row (sha256 guard)
    ──► text extraction (pdftotext -layout)
    ──► question parser   ──► questions (300)
    ──► solution parser   ──► answer key merge
    ──► section splitter  ──► chunks
    ──► embedding job     ──► chunk_embeddings
```

### Parsing hazards (observed in the 2026 file)

- Question blocks for tasks 1, 3 and 5 use **two columns**; naive line order interleaves them.
- Question numbers sometimes sit on a line **above** the stem.
- Ligatures (`ﬁ`, `ﬂ`), curly apostrophes, and hyphenated line breaks.
- The solutions table is **five columns**, and cells do not read in visual order.
- Some questions are true/false with exactly two options — the parser must not assume three.
- Source typos exist (`1031` "municiales", `3002` "capital la Comunidad"). **Never auto-correct.** Store verbatim, flag in `notes`, and surface in the review report, because the real exam is clean and a typo trains the wrong habit.

### Validation invariants (hard failure)

1. Exactly 300 questions; IDs contiguous within each task range.
2. Every question has 2 or 3 options; `kind` matches the option count.
3. Every question has an answer letter present in its options.
4. No duplicate IDs after re-ingestion; SHA-256 guards repeated runs.
5. Every question's `source_page` is within document bounds.
6. Chunk coverage: every page that contains prose belongs to at least one chunk.

Output: a review report (`docs/reports/ingest.md`) with counts per task and a list of any flagged items. A failed invariant stops CI; a flagged typo does not.

### Chunking

- Split on headings, not character counts. Target 300–500 tokens, ~15% overlap.
- Prepend the heading path to chunk text so embeddings see *"Tarea 1 → Las Cortes Generales → …"*.
- Keep figure captions as their own chunks (they are frequently the only place a fact appears).
- Store `page_from`/`page_to` for citations.

---

## 9. Exam engine

### Sampling

Stratified, never uniform:

```python
QUOTA = {1: 10, 2: 3, 3: 2, 4: 3, 5: 7}   # sums to 25
```

- **Campaign mode:** 12 fixed slots. Slot *k* draws from `pool[task][k*quota : (k+1)*quota]` after a seeded shuffle of each pool. Result: 12 disjoint exams covering all 300 questions exactly once.
- **Random mode:** stratified sampling from full pools, no overlap within a single exam.
- **Practice mode:** single task, user-chosen size.

### Fidelity rules

- 45-minute countdown, server-stamped `started_at`, grace period of 10 s before auto-submit.
- No negative marking; blank counts as wrong.
- Answers are never sent with the question payload. Scoring is server-side.
- Review screen shows per-task breakdown, because candidates commonly fail by bleeding Task 1 points.

---

## 10. Retrieval and generation

### Retrieval configuration ladder

Each step is a measurable increment, not a preference:

| Config | Components |
|---|---|
| `dense` | bge-m3 embeddings, cosine |
| `bm25` | Postgres `tsvector` (Spanish config) |
| `hybrid` | RRF fusion, k=60 |
| `hybrid+rerank` | cross-encoder rerank of top 20 → top 5 |

With ~300 chunks and 150–300 sections, `hybrid+rerank` is affordable and is expected to be the production config. The ladder exists so the eval can prove it.

### Hard filters

`WHERE task = $task` before retrieval. A Task 1 question must never be explained from Task 5 content. This is the highest-value single line in the retrieval path.

### Query construction

Never embed the raw stem. Compose:

```
"{stem}" — respuesta correcta: "{correct option}" — {task label} — {section hint}
```

Measure the gain as an ablation, then freeze it.

### Generation contract

Structured output, validated by Pydantic:

```python
class Explanation(BaseModel):
    summary: str                 # 1–2 sentences
    why_correct: str
    why_others_wrong: list[str]  # one entry per distractor
    citations: list[Citation]    # chunk_id, page, section
    confidence: float
```

Post-validation, deterministic:

- every `citation.chunk_id` must be in the retrieved set;
- the explanation must not assert an option other than the official key (checked by the judge, and by a cheaper string/letter heuristic as a first pass);
- length and language constraints (Spanish, 60–180 words for `summary` + `why_correct`).

### Precomputation

All 300 explanations are generated in a batch job, reviewed by sampling, and served from Postgres. The request path performs no generation. Live generation exists only for the tutor.

---

## 11. Model provider layer

One protocol, thin adapters, official SDKs confined to the adapters.

```python
class LLMProvider(Protocol):
    name: str
    async def complete(self, req: CompletionRequest) -> CompletionResult: ...
    def stream(self, req: CompletionRequest) -> AsyncIterator[str]: ...
    async def embed(self, texts: list[str], model: str) -> list[list[float]]: ...
```

`CompletionRequest` carries a canonical `json_schema`, `temperature=0`, `seed`, and `role`. `CompletionResult` carries text, parsed payload, exact provider `model_id`, usage, computed `cost_eur` and latency.

### Registry (config, not code)

```yaml
# api/app/llm/models.yaml
providers:
  mistral: { api_key_env: MISTRAL_API_KEY }
  openai:  { api_key_env: OPENAI_API_KEY }
  local:   { kind: ollama, base_url: "http://ollama:11434" }   # dev only

models:
  gen-mistral: { provider: mistral, model: mistral-small-latest, in_eur: 0.20, out_eur: 0.60 }
  gen-openai:  { provider: openai,  model: gpt-4.1-mini,         in_eur: 0.40, out_eur: 1.60 }
  judge:       { provider: openai,  model: gpt-4o-mini, json: true }
  embed-local: { provider: local,   model: bge-m3, kind: embedding }

routes:                     # ordered candidates; first success wins
  explain: [gen-mistral, gen-openai]
  tutor:   [gen-mistral, gen-openai]
  judge:   [judge]
  embed:   [embed-local]
```

Prices live in config and are used to write `llm_usage.cost_eur` per call. Verify them when they change; they are inputs, not truths.

### Fallback and resilience

- Triggers: 429, 5xx, connect/read timeout, malformed JSON after one repair attempt.
- `tenacity` retry with jitter, honouring `Retry-After`; bounded attempts.
- Per-provider circuit breaker: open after 5 consecutive failures, half-open after 60 s.
- `fell_back` recorded per call and exported as a counter.

### Development modes

| Mode | Use |
|---|---|
| `cassette` | Replay recorded responses keyed by prompt hash. Default for tests and CI. |
| `local` | Ollama on the developer machine. Plumbing checks only. |
| `live` | Real APIs. Nightly smoke tests and batch jobs. |

**Ollama is developer-machine only.** It is not part of the production compose file: on a CPU-only VPS a 7B model produces 2–5 tok/s, would spend a day on the 300-question batch, competes with `api` and `postgres` for RAM and cores, and is an unauthenticated endpoint. Local models are excluded from the published scorecard.

---

## 12. Evaluation

The eval harness is the portfolio centrepiece. It lives in `api/app/evals`, runs from the same container image as production, and writes results to `eval_runs`.

### Golden set

`evals/golden/questions.yaml`, 50 items to start (10 per task), 100 by v1.1:

```yaml
- question_id: "1016"
  relevant_sections: ["t1/cortes-generales", "t1/senado"]
  reference_es: "El Senado es la cámara de representación territorial..."
  probes: [distractors]
  difficulty: medium
```

Plus 10 **out-of-scope probes** ("¿Cuál es la capital de Francia?") to test abstention.

### Metrics

**Retrieval** (deterministic, no LLM): recall@5, MRR@10, nDCG@10, task-filter hit rate, reported per task and overall.

**Generation** (LLM judge, 3-point rubric):

| Metric | Definition | Failure it catches |
|---|---|---|
| `citation_support_rate` | share of cited chunks that actually support the claim | decorative citations |
| `key_agreement` | explanation argues for the official key | confident wrong answers |
| `faithfulness` | claims traceable to retrieved context | hallucination |
| `distractor_coverage` | all wrong options addressed | half-explanations |
| `abstention_accuracy` | refusal rate on out-of-scope probes | invention |

### Rigor requirements

- Bootstrap 95% confidence intervals on every metric; n=50 is small and the report says so.
- **Judge calibration:** 30 human-labelled items, report Cohen's κ. A judge below κ≈0.6 is not trusted, and the report states that.
- **Cross-judging:** Mistral generates, OpenAI judges (v1). When both generate, judge with both and publish the disagreement, because a model judging its own output is a known bias.
- Report cost and p50/p95 latency alongside quality; a Pareto frontier is rendered to `docs/reports/pareto.svg`.

### Gates

CI fails when `recall@5 < 0.85` or `citation_support_rate < 0.90` on the frozen golden set. A weekly cron re-runs the suite against live providers to detect model drift, with results written to `eval_runs` so trends are visible.

---

## 13. Observability and cost

- **Tracing:** OpenTelemetry instrumentation once, exported over OTLP. v1 backend is Langfuse Cloud (free tier), because it renders LLM-specific spans (retrieved chunk IDs, prompt, tokens, cost) without hosting ClickHouse on a small VPS. Backend is an env var, so self-hosted Langfuse, Tempo or Honeycomb is a config change.
- **Metrics:** Prometheus client at `/metrics` — request latency, cache hit rate, LLM calls by provider/model, `fell_back` count, tokens and euros per day, quota rejections. Scraped by whatever already runs; otherwise a single Grafana container.
- **Costs:** `make costs` renders a table from `llm_usage`. The README states cost per explanation, cost to rebuild all 300, and monthly baseline.
- **Logs:** structured JSON, one line per request, request ID propagated from Traefik.

Expected spend: a few euro for the full 300-explanation precompute, plus judge calls during development. Embeddings run locally, so they are free.

---

## 14. Containerisation

Everything runs in Docker, in all three environments.

### Images

- `api`: multi-stage, `python:3.12-slim`, `uv sync --frozen --no-dev`, cache mounts on `/root/.cache/uv`, non-root user, `HEALTHCHECK` on `/health`.
- `web`: `node:22-alpine` build stage → `nginx:1.27-alpine` serving static `dist/`.
- `.dockerignore` excludes `data/manual/`, `.env`, `.venv`, `node_modules`, `evals/reports/` — smaller context and no copyrighted material in layer history.

### Compose layering

```bash
docker compose -f compose.yml -f compose.dev.yml  up --build
docker compose -f compose.yml -f compose.prod.yml up -d
```

| File | Contents |
|---|---|
| `compose.yml` | shared service definitions, healthchecks, `init: true`, logging caps, `stop_grace_period` |
| `compose.dev.yml` | bind mounts, `--reload`, published ports, `develop.watch`, `ollama` under profile `local-llm` |
| `compose.prod.yml` | GHCR images by SHA, `pull_policy: always`, Traefik labels, `mem_limit`, no published ports |
| `compose.local-gpu.yml` | `--gpus all` for `ollama`, developer machine only |

Logging must be capped (`max-size: 10m`, `max-file: 3`) or the VPS disk fills. `mem_limit` on `api` and `postgres`, `shm_size: 256mb` for the DB.

### Jobs are containers

```makefile
ingest:     docker compose run --rm api python -m app.jobs.ingest /data/manual/manual-2026.pdf
index:      docker compose run --rm api python -m app.jobs.build_index --model bge-m3
precompute: docker compose run --rm api python -m app.jobs.precompute --models gen-mistral,gen-openai
eval:       docker compose run --rm api python -m evals.run --config hybrid+rerank
scorecard:  docker compose run --rm api python -m evals.scorecard > docs/reports/scorecard.md
```

No Celery, no Redis. There is no queue to operate for 300 rows, and the README says so.

### Migrations

A dedicated one-shot `migrate` service, run explicitly by `make migrate` (local) and by the deploy script (prod) **before** the API restarts. Not an entrypoint — entrypoints race on restart and on scale-out.

---

## 15. Deployment and operations

| Concern | Decision |
|---|---|
| Host | existing Hetzner VPS; Traefik already running as edge |
| Domain | `ccse-prep.tudorache.me` (prod), `staging.ccse-prep.tudorache.me` |
| Certificates | Traefik resolver; note a `*.tudorache.me` wildcard covers one label only, so staging needs its own SAN or HTTP-01 |
| Routing | `Host(...)&&PathPrefix(/api)` → api (priority 100); `Host(...)` → web (priority 10) |
| Networks | external `proxy` for Traefik, internal network for api↔postgres; postgres never on `proxy` |
| Registry | GHCR, immutable tags by commit SHA, `latest` as a convenience only |
| Deploy | Actions → build/push → `ssh` → `pull` + `up -d --remove-orphans` → health check gate |
| Rollback | `TAG=<previous-sha> docker compose up -d`; documented and rehearsed |
| Backups | nightly `pg_dump` → restic → Hetzner Storage Box; restore drill in the sprint |
| Hardening | non-root containers, `cap_drop: ALL`, `no-new-privileges`, ufw, fail2ban, unattended-upgrades |

Traefik gotchas to encode in `infra/`:

- `traefik.docker.network: proxy` on every service — a container on two networks otherwise gets the wrong IP and 502s.
- Explicit router `priority`, or the host-only router swallows `/api`.
- FastAPI serves its routes already prefixed with `/api`; no strip-prefix middleware. Frontend and API are same-origin, so no CORS at all.

---

## 16. Security and privacy

- No accounts; an anonymous UUID cookie, `HttpOnly`, `Secure`, `SameSite=Lax`, 180-day expiry.
- No PII collected. Attempts are analytics, not identity.
- Tutor endpoint: per-anonymous-user daily quota and token budget enforced in Postgres; Traefik rate limit is per-IP abuse protection only.
- Secrets via `.env` written by the deploy step from GitHub secrets; never in images, never in the repo. Rotation documented.
- `/api` sends `X-Robots-Tag: noindex`; admin/review routes bound to a path that Traefik does not expose.
- Dependency and image scanning: Trivy on HIGH/CRITICAL, SBOM and provenance attestations on push.

---

## 17. Sprint plan

Part-time, one week per sprint. Every sprint ends deployable.

| Sprint | Deliverable | Definition of done |
|---|---|---|
| **0 — Skeleton** | repo, `uv`, FastAPI `/health`, Postgres+pgvector, Alembic, Dockerfiles, compose layering, CI, Traefik deploy | `https://ccse-prep.tudorache.me/health` green from a GitHub Actions deploy, rollback rehearsed |
| **1 — Data** | PDF ingest, question parser, solution merge, chunker, validation report, 10-question sample committed | `make ingest` idempotent; 300/300 questions pass invariants; typo flags reviewed |
| **2 — Exam engine** | stratified sampler, server-side scoring, campaign slots 1–12, Astro UI with timer and review screen | 12 disjoint mocks verified by a test; a full 45-minute run works on mobile |
| **3 — Explanations** | provider layer, registry, fallback, hybrid retrieval + rerank, precompute job for 300 | every question has a cited explanation; no request-path generation |
| **4 — Evaluation** | golden set, harness, judge calibration, model matrix, scorecard, CI gate | ablation table + κ published in README; gate blocks a deliberately regressed PR |
| **5 — Operations** | tracing, `/metrics`, dashboard, quotas, staging environment, backups + restore drill, image scanning | dashboard screenshot with real cost/latency numbers; restore drill recorded |
| **6 — Story** | `architecture.md`, 5 ADRs, README with scorecard, 60-second demo GIF, short write-up | a reviewer can evaluate the project in three minutes |

Ordering rationale: 0 and 1 are chores that make everything after them cheap. Sprint 4 is the actual portfolio. Sprints 5–6 turn "I built a RAG app" into "I can run one", and double as DevOps practice on something that matters to you.

---

## 18. Decision log

| # | Decision | Rationale |
|---|---|---|
| D1 | Questions stored structured, not retrieved | A fixed bank with an answer key must be deterministic; retrieval adds failure modes and no value |
| D2 | Stratified sampling, not uniform 25-from-300 | Only stratified sampling reproduces the exam blueprint; the pool sizes divide cleanly into 12 exams |
| D3 | Server-side scoring | Keeps the key out of the browser; gives a reason to persist sessions |
| D4 | Precomputed explanations, live tutor only | Cost and latency predictability; the batch is reviewable before publication |
| D5 | No LangChain/LlamaIndex | The pipeline is ~300 lines; owning it is the signal, and every step is explainable in an interview |
| D6 | Two providers, one protocol | Demonstrates abstraction and enables a measured quality/cost comparison |
| D7 | Cross-provider judging | Avoids self-preference bias; disagreement is reportable evidence |
| D8 | Local embeddings (bge-m3) | Zero marginal cost, strong Spanish, no data leaves the host |
| D9 | No ANN index at this corpus size | A sequential scan is microseconds; premature indexing would be noise |
| D10 | Jobs as containers, no queue | No Redis/Celery for 300 rows; operational simplicity is a feature |
| D11 | Ollama dev-only | CPU inference cannot serve production, and an unauthenticated inference port is a liability |
| D12 | Goldens + CI gate from sprint 4 | Quality claims without measurement are the main failure mode of portfolio RAG projects |
| D13 | `tsvector` + GIN for lexical search | The corpus is dense with proper nouns where BM25 beats dense retrieval |
| D14 | Full bank server-side, sample in git | Redistribution of © material is avoided while keeping the demo complete |

---

## 19. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| PDF layout breaks the parser | medium | invariants fail loudly; review report; fixes isolated in `ingest/` |
| Judge scores are not trustworthy | medium | κ against 30 human labels; publish it honestly |
| Small golden set (n=50) overfits | high | CIs on everything; grow to 100; never tune prompts against the same 50 twice without holding out 15 |
| Provider price/API drift | medium | registry config, `model_id` recorded, nightly smoke tests |
| Scope creep into accounts/features | high | non-goals section above is binding for v1 |
| Legal complaint from rights holder | low | non-commercial, attributed, no bulk export, one-command teardown |
| VPS resource contention | medium | `mem_limit`, no local inference in prod, capped logs |

---

## 20. Appendix A — commands

```bash
make up            # dev stack (api, web, postgres)
make up-local-llm  # + ollama on the developer machine
make migrate       # alembic upgrade head
make ingest PDF=...  # 300 questions + chunks
make index         # embeddings
make precompute    # explanations for all questions
make eval          # golden-set run
make scorecard     # regenerate docs/reports/scorecard.md
make costs         # cost table from llm_usage
make test          # unit + cassettes
make deploy        # prod (called by CI, never by hand)
```

## Appendix B — metric definitions

| Metric | Formula |
|---|---|
| recall@5 | share of golden items where ≥1 `relevant_section` appears in the top 5 |
| MRR@10 | mean of 1/rank of the first relevant chunk |
| task-filter hit rate | share of retrievals where every returned chunk has the question's `task` |
| citation_support_rate | judged-supported citations / total citations |
| key_agreement | items where the explanation argues for the official key / n |
| faithfulness | judged claims entailed by retrieved context / total claims |
| abstention_accuracy | correct refusals on out-of-scope probes / 10 |

## Appendix C — verified source facts

- PDF: 102 pages, A4, text layer present, produced 2026-01-15, © Instituto Cervantes.
- Bank: 300 questions, ranges as in §3.
- Solutions: pages 99–101, five columns per task.
- Formatting: tasks 1/3/5 question blocks two-column; task 2 true/false with two options.


---

## 21. Implementation status (v1)

Shipped in one pass. Where reality diverged from this plan, the divergence is
recorded here rather than quietly edited above.

| Sprint | State | Notes |
|---|---|---|
| 0 — Skeleton | done | FastAPI + Astro + Postgres, compose overlays, CI, Traefik labels, rollback script |
| 1 — Data | done | 300/300 questions and answer key parsed, 0 invariant errors, 53 chunks |
| 2 — Exam engine | done | 12 disjoint campaign exams verified, server-side scoring, exam UI with timer |
| 3 — Explanations | done | hybrid retrieval, precomputed for all 300; extractive fallback when no key |
| 4 — Evaluation | done | 40-item golden set, four configs × two query modes, CIs, scorecard, CI gate |
| 5 — Operations | partial | `/metrics`, quotas, backups, image scanning, deploy script; staging and live deploy not exercised from here |
| 6 — Story | done | README, architecture, 5 ADRs, generated scorecard |

Deliberate deviations:

- **Golden set lives in `api/app/evals/`**, not a root `evals/` package: it must be
  inside the image to run in CI, and a second Python package would need its own
  build context.
- **Cross-encoder reranking replaced by a lexical reranker.** A torch-based
  cross-encoder would multiply image size; the ONNX encoder is already used for
  embeddings. The scorecard reports the lexical variant's numbers honestly.
- **HTTP adapters instead of vendor SDKs** (ADR 0004).
- **No announcement workflow for explanations.** They are generated as `draft`
  and served immediately; the `status` column exists for a review step that v1
  does not implement.
- **Correction timing is a per-exam setting** (added after v1): `feedback=end`
  is the default; `feedback=immediate` is practice-only and reveals verdicts one
  question at a time through `/api/exams/{id}/check`, so the key is never sent
  with the questions. Timed mocks are untouched.
- **Practice drills are untimed** (added after v1): `all: true` returns the whole
  task with `expires_at = null`, and the UI counts up instead of down. Mock exams
  keep the 45-minute limit. Draft answers live in memory only, so a refresh ends
  the run — a deliberate scope cut.
- **Tracing is not wired to a backend.** The metrics endpoint and structured
  logs are in place; OTLP export is a configuration step on the VPS, not code
  that could be verified here.
