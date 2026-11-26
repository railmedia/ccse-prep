FROM python:3.12-slim AS base
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"
# Upgrade first: the slim base lags on Debian point releases, and Trivy fails
# the build on fixable HIGH/CRITICAL packages (e.g. libzstd, zlib).
RUN apt-get update \
 && apt-get upgrade -y \
 && apt-get install -y --no-install-recommends curl poppler-utils \
 && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /uvx /usr/local/bin/
WORKDIR /app

# --- dependencies -----------------------------------------------------------
# Kept in a separate layer so source edits never invalidate the venv.
FROM base AS deps
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project

# --- development: source is bind-mounted, dependencies are not --------------
FROM base AS dev
COPY --from=deps /opt/venv /opt/venv
COPY pyproject.toml uv.lock ./
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# --- production -------------------------------------------------------------
FROM base AS prod
COPY --from=deps /opt/venv /opt/venv
COPY . .
ENV FASTEMBED_CACHE_PATH=/opt/hf \
    HF_HOME=/opt/hf
# Bake the embedding model into the image: ~470 MB of weights, but no cold-start
# download and no runtime dependency on the Hugging Face Hub.
RUN python -c "from fastembed import TextEmbedding; \
    TextEmbedding(model_name='sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2')" \
 && useradd --create-home --uid 10001 app \
 && chown -R app:app /app /opt/hf
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/health || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
