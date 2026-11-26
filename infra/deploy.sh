#!/usr/bin/env bash
#
# Deploy one release on the host that runs Traefik.
#
# Called over SSH by .github/workflows/ci.yml, and runnable by hand:
#
#   TAG=$(git rev-parse HEAD) ./infra/deploy.sh
#
# Expects /opt/ccse-prep/.env to exist (provisioned once, never in git).

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

: "${TAG:?TAG must be set to the image tag to deploy}"

if docker compose version >/dev/null 2>&1; then
  COMPOSE=(docker compose)
else
  COMPOSE=(docker-compose)
fi

FILES=(-f infra/compose.yml -f infra/compose.prod.yml)
ENVFILE="${ENVFILE:-.env}"

if [[ ! -f "$ENVFILE" ]]; then
  echo "missing $ENVFILE — provision it on the host first" >&2
  exit 1
fi

read_env() {
  grep -E "^$1=" "$ENVFILE" | tail -1 | cut -d= -f2- || true
}

set_env() {
  local key="$1" value="$2"
  if grep -qE "^${key}=" "$ENVFILE"; then
    sed -i "s|^${key}=.*|${key}=${value}|" "$ENVFILE"
  else
    printf '%s=%s\n' "$key" "$value" >>"$ENVFILE"
  fi
}

PUBLIC_HOST="$(read_env PUBLIC_HOST)"
if [[ -z "$PUBLIC_HOST" ]]; then
  echo "PUBLIC_HOST is not set in $ENVFILE" >&2
  exit 1
fi

PREVIOUS_TAG="$(read_env TAG)"
PREVIOUS_TAG="${PREVIOUS_TAG:-latest}"

echo "==> deploying ${TAG} (previous: ${PREVIOUS_TAG}) on ${PUBLIC_HOST}"
set_env TAG "$TAG"

run_compose() {
  "${COMPOSE[@]}" "${FILES[@]}" --env-file "$ENVFILE" "$@"
}

echo "==> pulling images"
run_compose pull

echo "==> migrating"
run_compose --profile tools run --rm migrate

echo "==> starting"
run_compose up -d --remove-orphans

echo "==> waiting for health"
for attempt in $(seq 1 30); do
  if curl -fsS --max-time 5 "https://${PUBLIC_HOST}/api/health" >/dev/null; then
    echo "==> healthy after ${attempt} attempt(s)"
    exit 0
  fi
  sleep 2
done

echo "!! health check failed; rolling back to ${PREVIOUS_TAG}" >&2
set_env TAG "$PREVIOUS_TAG"
run_compose pull
run_compose up -d --remove-orphans
exit 1
