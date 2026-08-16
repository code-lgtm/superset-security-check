---
name: testing-docker
description: How to run and test the containerized webhook service (Docker, docker compose, Cloud Run PORT behavior) for superset-security-check.
---

# Testing the containerized webhook service

## Prereqs
- Docker is available on the box (`docker version`, compose v2 via `docker compose`).
- No real Devin credentials are needed for container testing. Create `.env` from `.env.example`
  with dummy values; only `WEBHOOK_SECRET` needs to be a value you know, e.g.:
  ```bash
  sed -e 's/^WEBHOOK_SECRET=.*/WEBHOOK_SECRET=test-secret-123/' \
      -e 's/^DEVIN_API_KEY=.*/DEVIN_API_KEY=dummy-api-key/' \
      -e 's/^DEVIN_ORG_ID=.*/DEVIN_ORG_ID=dummy-org/' .env.example > .env
  ```

## Run
```bash
docker build -t superset-security-check .
docker run -d --name ssc --env-file .env -p 5000:5000 superset-security-check
```
Cloud Run simulation: `docker run -d -e PORT=8080 -p 8080:8080 ...`; gunicorn must log
`Listening at: http://0.0.0.0:8080` (the CMD is shell-form so `$PORT` expands at runtime).

UI endpoints: `/dashboard` (HTML), `/metrics` (JSON), `/health` (JSON).

## Triggering a webhook without Devin credentials
The Devin API call fails with dummy creds; the handler still returns 200 and records a
synthetic session row (`session_id=webhook-<head_commit>`, status `failed`) which shows on
the dashboard. Signature is a raw HMAC-SHA256 hex of the exact body:
```bash
PAY='{"ref":"refs/heads/main","repository":{"full_name":"acme/demo"},"head_commit":{"id":"abc123"},"commits":[{"message":"m"}]}'
SIG=$(printf '%s' "$PAY" | openssl dgst -sha256 -hmac 'test-secret-123' | awk '{print $2}')
curl -s -X POST localhost:5000/webhook/commit -H 'Content-Type: application/json' \
  -H "X-Hub-Signature-256: sha256=$SIG" -d "$PAY"
```
A wrong signature must return 401.

## Named-volume permission pitfall
The container runs as non-root `appuser` (uid 10001). `docker-compose.yml` mounts a named
volume at `/data` with `SESSION_DB_PATH=/data/sessions.db`. If `/data` does not already exist
in the image owned by `appuser`, Docker creates the volume mountpoint as `root:root 755` and
every SQLite-backed route returns HTTP 500 (`sqlite3.OperationalError: unable to open database
file`). The Dockerfile therefore must do `mkdir -p /data && chown -R appuser:appuser /app /data`
(and ideally `VOLUME ["/data"]`) before `USER appuser`. If /dashboard or /metrics 500s under
compose, check `docker compose exec webhook ls -ld /data` first.

## Persistence check
`docker compose down` (WITHOUT `-v`) then `docker compose up -d` must keep the recorded session
on /dashboard; `docker compose down -v` wipes it. Free host port 5000 (`docker rm -f` any plain
`docker run` container) before starting compose, otherwise compose fails with
"port is already allocated".

## Unit tests
`.venv/bin/python -m pytest` from the repo root (10 tests).

## Devin Secrets Needed
None for container testing (dummy env values suffice).
