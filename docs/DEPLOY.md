# Deploying to the Hetzner host

One-time setup, then every deploy is a push to `main`.

```
GitHub Actions ──► GHCR (images, by commit SHA)
        │
        └──► ssh ──► /home/production/tudorache.me/ccse-prep
                       ├── .env          (provisioned once, never committed)
                       └── infra/        (rsynced by CI)
                              │
                              ├── deploy.sh    pull → migrate → up → health → rollback
                              └── bootstrap.sh manual → ingest → embed → precompute
                     Docker ──► existing Traefik (proxy network, entrypoint websecure, resolver le)
```

## Prerequisites (once)

| Item | Value used here |
|---|---|
| DNS | `ccse-prep.tudorache.me` → VPS IP |
| Traefik network | `proxy` (external) |
| Entrypoint / resolver | `websecure` / `le` |
| Deploy path | `/home/production/tudorache.me/ccse-prep` |
| SSH user | must be in the `docker` group and own the deploy path |
| GitHub secrets | `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY` |
| GitHub variable | `DEPLOY_PATH` = the path above |

The deploy job rsyncs only `infra/`, so the server does not need a git checkout —
just that directory and a `.env` next to it.

## 1. Server `.env`

```bash
mkdir -p /home/production/tudorache.me/ccse-prep
cd /home/production/tudorache.me/ccse-prep
cp /path/to/env.prod.example .env
# edit: POSTGRES_PASSWORD, and anything that differs from the defaults
chmod 600 .env
```

Required keys are documented in `env.prod.example`. `TAG` is rewritten by
`deploy.sh` on every deploy; everything else is yours.

## 2. First push

```bash
git push -u origin main
```

The workflow runs `api`, `web` and `compose`, then builds and pushes
`ghcr.io/railmedia/ccse-prep/{api,web}:<sha>` and `:latest`, then scans with Trivy.

The first `deploy` will fail at `docker compose pull` with **pull access denied**.
That is expected: GHCR packages are private by default even when the repository
is public.

## 3. Make the packages public (once)

GitHub → profile/org → **Packages** → `ccse-prep/api` → *Package settings* →
*Danger zone* → *Change visibility* → **Public**. Repeat for `ccse-prep/web`.

Verify from any machine:

```bash
docker logout ghcr.io
docker pull ghcr.io/railmedia/ccse-prep/api:latest
```

Then re-run the failed job: Actions → the run → **Re-run failed jobs**. (The
workflow also has a manual *Run workflow* trigger.)

## 4. What a deploy does

`infra/deploy.sh`, executed over SSH:

1. records the current `TAG` in `.env` as the rollback point;
2. writes the new `TAG`;
3. `docker compose pull`;
4. `alembic upgrade head` in a one-shot container;
5. `up -d --remove-orphans`;
6. polls `https://<host>/api/health` for up to 90 s;
7. on failure, restores the previous `TAG`, pulls and restarts, exits non-zero.

Nothing is published to the host; Traefik reaches the containers over `proxy`.
Migrations run before the API restarts, never in an entrypoint.

## 5. Load the data (once per manual edition)

A fresh database is empty: the site will be green and every exam request will
answer `400 question bank is empty`. Run:

```bash
ssh <user>@<host>
cd /home/production/tudorache.me/ccse-prep
./infra/bootstrap.sh
```

It downloads `MANUAL_URL` to `data/manual/`, then runs `ingest` → `embed` →
`precompute` in the production image, and prints the row counts. Roughly two to
three minutes; the ONNX model is already in the image, so there is no large
download.

- No `MISTRAL_API_KEY`/`OPENAI_API_KEY` → explanations come from the deterministic
  extractive fallback. Add a key later and run `./infra/bootstrap.sh --explanations`.
- A new manual edition: update `MANUAL_URL`/`MANUAL_YEAR`, run `--force`.

## 6. Verify

```bash
curl -s https://ccse-prep.tudorache.me/api/health
curl -s https://ccse-prep.tudorache.me/ready
```

Then in a browser: start a campaign exam, submit, open an explanation, and check
`https://ccse-prep.tudorache.me/metrics`.

## Rollback

Automatic on a failed health check. Manually:

```bash
ssh <user>@<host>
cd /home/production/tudorache.me/ccse-prep
TAG=<previous-sha> ./infra/deploy.sh
```

or Actions → *Run workflow* → `tag: <previous-sha>`. Migrations are forward-only;
if a release changed the schema, rolling back the image is safe (the old code
ignores the new column) but the reverse is not automatic.

## Backups

`infra/backup.sh` dumps and uploads to restic. Install once on the host:

```bash
export RESTIC_REPOSITORY=sftp:...   # or a local path for a first test
restic init
crontab -e
# 0 3 * * * cd /home/production/tudorache.me/ccse-prep && ./infra/backup.sh >> /var/log/ccse-backup.log 2>&1
```

Restore drill:

```bash
restic restore latest --target /tmp/restore
docker compose -f infra/compose.yml -f infra/compose.prod.yml exec -T postgres \
  pg_restore -U ccse -d ccse --clean --if-exists < /tmp/restore/.../ccse-*.dump
```

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `pull access denied` | package still private | step 3 |
| Deploy healthy but 404 from Traefik | wrong network or entrypoint | check `docker inspect` labels; `TRAEFIK_ENTRYPOINT` must exist |
| `/` 404 while `/api/health` is 200 | web container is **unhealthy**; Traefik excludes unhealthy backends | `docker inspect --format '{{.State.Health.Status}}' ccse-prep-web-1` — if unhealthy, check the health command (must use `127.0.0.1`, not `localhost`) |
| Health check times out on the first deploy | DNS or certificate not ready | `dig`, `docker logs traefik \| grep -i acme`; or `SKIP_HEALTHCHECK=1 ./infra/deploy.sh` for that first run |
| `question bank is empty` | data not loaded | `./infra/bootstrap.sh` |
| 502 from the API route | container crashed | `docker compose ... logs --tail=100 api` |
| Cookie not sent | `CCSE_COOKIE_SECURE=true` on plain HTTP | use HTTPS, or set it false locally |
| Migrations fail | DB credentials in `.env` | `docker compose ... exec postgres psql -U $POSTGRES_USER -d $POSTGRES_DB` |

## Costs

Public GHCR packages and Actions minutes for a public repo are free. The only
recurring cost is the VPS. LLM usage is zero while keys are empty; with a key,
regenerating all 300 explanations costs a few cents.
