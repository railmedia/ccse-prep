#!/usr/bin/env bash
#
# Nightly PostgreSQL backup: dump, compress, upload, prune.
#
# Install on the host (not in a container) as a cron/systemd timer:
#
#   0 3 * * *  cd /opt/ccse-prep && ./infra/backup.sh >> /var/log/ccse-backup.log 2>&1
#
# Requires: restic initialised against the target repository, and
# RESTIC_REPOSITORY / RESTIC_PASSWORD (or a restic env file) in the environment.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

: "${RESTIC_REPOSITORY:?set RESTIC_REPOSITORY (e.g. sftp:backup@host:/ccse)}"

if docker compose version >/dev/null 2>&1; then
  COMPOSE=(docker compose)
else
  COMPOSE=(docker-compose)
fi

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "==> dumping database"
"${COMPOSE[@]}" -f infra/compose.yml -f infra/compose.prod.yml --env-file .env \
  exec -T postgres pg_dump -U "${POSTGRES_USER:-ccse}" -d "${POSTGRES_DB:-ccse}" -Fc \
  >"$TMP/ccse-${STAMP}.dump"

echo "==> uploading to restic"
restic backup --tag ccse --host "$(hostname)" "$TMP/ccse-${STAMP}.dump"

echo "==> pruning (keep 7 daily, 4 weekly, 6 monthly)"
restic forget --tag ccse --keep-daily 7 --keep-weekly 4 --keep-monthly 6 --prune

echo "==> done: ccse-${STAMP}.dump"
