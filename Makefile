SHELL := bash
.DEFAULT_GOAL := help

# Docker Compose is v2 ("docker compose") on most hosts; some still ship the
# standalone binary. Detect once so every target works on both.
COMPOSE ?= $(shell docker compose version >/dev/null 2>&1 && echo "docker compose" || echo "docker-compose")

DEV  := $(COMPOSE) -f infra/compose.yml -f infra/compose.dev.yml
PROD := $(COMPOSE) -f infra/compose.yml -f infra/compose.prod.yml
ENVF := --env-file .env
TOOLS := --profile tools

.PHONY: help env up up-local-llm down logs ps build migrate shell psql \
        test test-all lint fmt typecheck check config-dev config-prod deploy build scan \
        ingest index precompute eval golden scorecard costs backup

help: ## Show this help
	@awk 'BEGIN {FS = ":.*?## "}; /^[a-zA-Z_-]+:.*?## / {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

env: ## Create .env from the example, with a generated database password
	@if [ -f .env ]; then echo ".env already exists"; else \
		cp .env.example .env && \
		sed -i "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$$(openssl rand -hex 16)|" .env && \
		echo "created .env (edit PUBLIC_HOST / IMAGE_PREFIX as needed)"; fi

up: env ## Start the dev stack
	$(DEV) $(ENVF) up -d --build

up-local-llm: env ## Dev stack plus local Ollama
	$(DEV) $(ENVF) --profile local-llm up -d --build

down: ## Stop the dev stack
	$(DEV) down

logs: ## Tail api logs
	$(DEV) logs -f --tail=100 api

ps: ## Show container status
	$(DEV) ps

build: ## Build both images (prod targets)
	docker build --target prod -t ccse-prep/api:dev api
	docker build --target prod -t ccse-prep/web:dev web

scan: ## Trivy-scan the local prod images (what CI gates on)
	@for image in ccse-prep/api:dev ccse-prep/web:dev; do \
		echo "==> $$image"; \
		docker run --rm -v /var/run/docker.sock:/var/run/docker.sock aquasec/trivy:latest image \
			--quiet --scanners vuln --severity HIGH,CRITICAL --ignore-unfixed "$$image" || exit 1; \
	done

migrate: ## Apply database migrations
	$(DEV) $(ENVF) $(TOOLS) run --rm migrate

shell: ## Shell inside the api container
	$(DEV) $(ENVF) run --rm --entrypoint /bin/sh api

psql: ## psql inside the postgres container
	$(DEV) exec postgres psql -U $${POSTGRES_USER:-ccse} -d $${POSTGRES_DB:-ccse}

test: ## Unit tests (no network, no database)
	$(DEV) $(ENVF) run --rm api pytest

test-all: ## Unit + integration tests (needs the database)
	$(DEV) $(ENVF) run --rm api pytest -m "integration or not integration"

lint: ## Lint and format check
	$(DEV) $(ENVF) run --rm api sh -c "ruff check . && ruff format --check ."

fmt: ## Format and autofix
	$(DEV) $(ENVF) run --rm api sh -c "ruff format . && ruff check --fix ."

typecheck: ## mypy (strict)
	$(DEV) $(ENVF) run --rm api mypy app

check: lint typecheck test ## What CI runs

config-dev: ## Validate the dev compose model
	$(DEV) $(ENVF) config >/dev/null && echo "dev compose OK"

config-prod: ## Validate the prod compose model
	$(PROD) $(ENVF) config >/dev/null && echo "prod compose OK"

deploy: ## Deploy the current commit to the VPS
	TAG=$$(git rev-parse HEAD) ./infra/deploy.sh

# --- data and evaluation ----------------------------------------------------
PDF ?= /data/manual/manual-ccse-2026.pdf

ingest: ## Parse the manual into questions and chunks (PDF=/path/in/container)
	$(DEV) $(ENVF) run --rm api python -m app.jobs.ingest $(PDF)

index: ## Build chunk embeddings
	$(DEV) $(ENVF) run --rm api python -m app.jobs.embed

precompute: ## Generate explanations for all questions
	$(DEV) $(ENVF) run --rm api python -m app.jobs.precompute

eval: ## Run the golden-set evaluation (writes docs/reports/scorecard.md)
	mkdir -p docs/reports
	$(DEV) $(ENVF) run --rm -e GIT_SHA=$$(git rev-parse --short HEAD) api \
		python -m app.evals.run > docs/reports/scorecard.md

golden: ## Rebuild the golden retrieval set (deliberate, review the diff)
	$(DEV) $(ENVF) run --rm api python -m app.evals.build_golden

scorecard: eval ## Alias: regenerate the published scorecard

costs: ## Render the LLM cost table
	$(DEV) $(ENVF) run --rm api python -m app.jobs.costs

backup: ## Nightly database backup (needs RESTIC_REPOSITORY on the host)
	./infra/backup.sh
