# CCSE Prep

Study app for the Spanish **CCSE** exam (*Conocimientos Constitucionales y Socioculturales de España*), the civics test required for Spanish nationality.

Sit full 25-question mock exams under real conditions — 45 minutes, 15/25 to pass, no negative marking — then get an explanation for every question, grounded in the official preparation manual with page citations.

> Unofficial, non-commercial project. Not affiliated with the Instituto Cervantes, which holds the rights to the manual and the question bank.

---

## What it does

- **Blueprint-faithful mocks.** Sampling is stratified per task (10/3/2/3/7), not uniform. The bank's pools are exactly 12× the quotas, so campaign mode generates **12 disjoint exams covering all 300 questions once**.
- **Practice by task.** Ten questions at random, or the whole task (24–120 questions) untimed, with a stable id order so you can work through it.
- **Deferred or immediate correction.** Drills can correct everything on submit, or reveal each verdict (and its manual citation) the moment you answer — via a per-question check endpoint, so the key still never ships with the questions.
- **Dark and light themes**, following the OS on first visit and remembered per browser.
- **Server-side scoring.** The answer key never reaches the browser before submission.
- **Grounded explanations.** Retrieval over the manual, hard-filtered by task, with citations to page and section. Precomputed for all 300 questions; the request path does no generation.
- **Measured retrieval.** A golden set, four configurations, bootstrap confidence intervals, and a published scorecard regenerated from the database.
- **Degrades honestly.** No API key → deterministic extractive explanations, clearly labelled. Keys present → Mistral/OpenAI behind one protocol, with fallback and circuit breaking.

## Results

From [`docs/reports/scorecard.md`](docs/reports/scorecard.md) (40-item golden set, 95% bootstrap CIs):

| config | recall@5 (stem only) | MRR@10 |
|---|---|---|
| `dense` (multilingual MiniLM, CPU) | 0.850 | 0.649 |
| `bm25` (Postgres `tsvector`) | 0.325 | 0.312 |
| `hybrid` (RRF) | 0.875 | 0.707 |
| `hybrid+rerank` | 1.000 | 0.865 |

Read the caveats in the report before quoting these: the corpus is small, T2 cannot be labelled by containment, and the label rule is mechanical (the chunk contains the correct option verbatim) rather than human judgement.

## Architecture

Two data planes, deliberately separated: questions and the answer key are exact and relational; the manual is chunked, embedded and retrieved only to explain. See [`docs/architecture.md`](docs/architecture.md) and the [ADRs](docs/adr/).

```
Astro (static) ──► FastAPI ──► Postgres 17 + pgvector ──► MiniLM embeddings (local, CPU)
                      │
                      └──► Mistral / OpenAI (optional, per-role fallback)
```

## Stack

FastAPI · SQLAlchemy 2.0 · Alembic · Postgres 17 + pgvector · fastembed (ONNX) · Astro · uv · Docker Compose · GitHub Actions → GHCR → Hetzner/Traefik

## Quickstart

```bash
make env     # creates .env with a generated DB password
make up      # api :8000, web :4321, postgres :5432
make migrate # schema

# data pipeline (the manual is not committed)
curl -sSL -o data/manual/manual-ccse-2026.pdf \
  "https://cervantes.org/sites/public/produccion/files/2026-10/manual-preparacion-prueba-ccse-2026.pdf"
make ingest      # PDF → 300 questions + 53 chunks (fails loudly on invariant breaks)
make index       # chunk embeddings
make precompute  # explanations for all 300 questions
```

- App: <http://localhost:4321>
- API docs: <http://localhost:8000/api/docs>
- Readiness: <http://localhost:8000/ready>
- Metrics: <http://localhost:8000/metrics>

```bash
make check    # ruff + mypy (strict) + unit tests
make test-all # unit + database-backed integration tests
make eval     # golden-set evaluation → docs/reports/scorecard.md
make costs    # LLM cost table from llm_usage
```

Ports are overridable in `.env` (`API_PORT`, `WEB_PORT`, `POSTGRES_PORT`).

## Adding model providers

Roles are resolved from `api/app/llm/models.yaml`, in order, skipping providers without a key:

```yaml
routes:
  explain: [gen-mistral, gen-openai, local-qwen]
  tutor:   [gen-mistral, gen-openai, local-qwen]
```

```bash
# .env
MISTRAL_API_KEY=...        # used by default
OPENAI_API_KEY=...         # fallback, and the judge in evals
```

```bash
make precompute   # now generates with the model instead of the extractive fallback
make eval         # compare configurations and models over identical questions
```

Local inference is opt-in and developer-machine only:

```bash
LOCAL_LLM_ENABLED=true make up-local-llm
docker compose -f infra/compose.yml -f infra/compose.dev.yml --profile local-llm \
  exec ollama ollama pull qwen2.5:3b-instruct
```

## Repository layout

```
api/app/
  ingest/    PDF → questions, answer key, sections      (bbox-based, two-column aware)
  exam/      stratified sampler, server-side scoring
  rag/       embeddings, hybrid search, rerank, prompts, extractive fallback
  llm/       provider protocol, adapters, registry, routing
  evals/     golden set builder, harness, scorecard renderer
  jobs/      ingest, embed, precompute, costs
  routers/   exams, questions, tutor, health, metrics
web/         Astro pages: landing + exam runner (vanilla JS, no framework)
infra/       compose overlays, Traefik labels, deploy, backup
docs/        plan, architecture, ADRs, generated reports
```

## Data and licensing

The CCSE manual and question bank are © Instituto Cervantes. This repository ships the **ingestion pipeline** and the **golden-set metadata**, not the bank: the manual is downloaded by whoever runs the app and the questions live in Postgres. `data/manual/` is gitignored, and the full bank is never committed or baked into an image.

## Deployment

Full runbook: [`docs/DEPLOY.md`](docs/DEPLOY.md).

CI builds both images on push to `main`, pushes them to GHCR tagged with the commit SHA, scans with Trivy, then rsyncs `infra/` to the host and runs `./infra/deploy.sh`: pull → `alembic upgrade head` → restart → health check through the public URL → **rollback to the previous tag on failure**.

```bash
# on the server, once
mkdir -p /home/production/tudorache.me/ccse-prep
cp env.prod.example /home/production/tudorache.me/ccse-prep/.env   # then edit it

# after the first successful image build: make the GHCR packages public
# (Packages → ccse-prep/api → Package settings → Change visibility)

# then load the data: a fresh database has no questions
cd /home/production/tudorache.me/ccse-prep && ./infra/bootstrap.sh
```

| Kind | Name | Purpose |
|---|---|---|
| secret | `DEPLOY_HOST` / `DEPLOY_USER` / `DEPLOY_SSH_KEY` | SSH access |
| variable | `DEPLOY_PATH` | `/home/production/tudorache.me/ccse-prep` |

The weekly `eval` workflow downloads the manual, ingests it, embeds it and fails if `hybrid+rerank` recall@5 drops below 0.85. Nightly backups: `infra/backup.sh` (pg_dump → restic).
