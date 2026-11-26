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

diagnose() {
  echo "--- containers ---" >&2
  run_compose ps >&2 || true
  docker ps -a --filter "name=ccse-prep-" \
    --format '{{.Names}}\t{{.Status}}\t{{.Image}}' >&2 || true

  for service in web api; do
    cid="$(run_compose ps -q "$service" 2>/dev/null || true)"
    [ -n "$cid" ] || continue
    echo "--- $service ---" >&2
    docker inspect "$cid" --format 'state={{.State.Status}} exit={{.State.ExitCode}}' >&2 || true
    docker inspect "$cid" --format 'capdrop={{json .HostConfig.CapDrop}}' >&2 || true
    docker inspect "$cid" --format '{{json .NetworkSettings.Networks}}' >&2 || true
    docker inspect "$cid" --format '{{json .Config.Labels}}' \
      | tr ',' '\n' | grep -i traefik >&2 || true
    docker logs --tail=25 "$cid" >&2 2>&1 || true
  done

  traefik="$(docker ps --format '{{.Names}}' | grep -i traefik | head -1 || true)"
  if [ -n "$traefik" ]; then
    echo "--- traefik ($traefik) ---" >&2
    docker logs "$traefik" --tail=80 2>&1 | grep -i -E 'ccse|error' | tail -20 >&2 || true
  else
    echo "--- no traefik container found by name ---" >&2
  fi
}

echo "==> waiting for health"
if [[ "${SKIP_HEALTHCHECK:-0}" == "1" ]]; then
  echo "!! SKIP_HEALTHCHECK=1 — not verifying, not rolling back"
  exit 0
fi

ATTEMPTS="${HEALTH_ATTEMPTS:-45}"
api_ok=0
web_ok=0
for attempt in $(seq 1 "$ATTEMPTS"); do
  api_ok=0
  web_ok=0
  curl -fsS --max-time 5 "https://${PUBLIC_HOST}/api/health" >/dev/null && api_ok=1
  # The static frontend has its own router; a dead web container must not pass.
  curl -fsS --max-time 5 -o /dev/null "https://${PUBLIC_HOST}/" && web_ok=1
  if [ "$api_ok" = 1 ] && [ "$web_ok" = 1 ]; then
    echo "==> healthy after ${attempt} attempt(s)"
    exit 0
  fi
  sleep 2
done

echo "!! health check failed (api=${api_ok} web=${web_ok}); rolling back to ${PREVIOUS_TAG}" >&2
diagnose
echo "   check, in order:" >&2
echo "   - DNS:   dig +short ${PUBLIC_HOST}" >&2
echo "   - cert:  docker logs traefik 2>&1 | grep -i -m5 acme" >&2
echo "   - net:   docker inspect --format '{{json .NetworkSettings.Networks}}' \$(docker compose -f infra/compose.yml -f infra/compose.prod.yml --env-file .env ps -q api)" >&2
echo "   - logs:  docker compose -f infra/compose.yml -f infra/compose.prod.yml logs --tail=50 api" >&2
set_env TAG "$PREVIOUS_TAG"
run_compose pull
run_compose up -d --remove-orphans
exit 1
