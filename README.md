# superset-security-check

This repository is a minimal webhook template for handling commit events from a Git hosting provider and creating a Devin session from each push.

## What it does

- Receives a POST webhook request at /webhook/commit
- Verifies the HMAC signature using the shared secret
- Parses the push payload and extracts repository, branch, and commit information
- Calls the Devin API to create a session for the commit
- Includes the optional playbook ID when configured

## Documentation

Detailed docs live in [docs/README.md](docs/README.md), covering the
[architecture](docs/architecture.md), [configuration](docs/configuration.md), and the
[dashboard and metrics endpoints](docs/dashboard.md).

## Environment variables

Copy [.env.example](.env.example) to `.env` and fill in your values:

```bash
cp .env.example .env
```

```bash
WEBHOOK_SECRET=your-github-webhook-secret
DEVIN_API_KEY=your-devin-api-key
DEVIN_ORG_ID=your-devin-organization-id
DEVIN_PLAYBOOK_ID=your-devin-playbook-id
DEVIN_API_BASE_URL=https://api.devin.ai/v3
PORT=5000
```

## Run locally

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
set -a
. ./.env
set +a
python webhook.py
```

Then expose the local service with ngrok and configure GitHub webhook settings.

Or use the provided startup script:

```bash
./run.sh
```

## Run with Docker

Build the image and run it with your local environment file:

```bash
docker build -t superset-security-check .
docker run --env-file .env -p 5000:5000 superset-security-check
```

The container runs gunicorn against `webhook:app` and binds to `0.0.0.0:$PORT`
(`PORT` defaults to 5000), so the same image works locally and on Cloud Run.
To publish on a different host port, map it explicitly, for example
`docker run --env-file .env -e PORT=8080 -p 5000:8080 superset-security-check`.

Or use Docker Compose, which builds the image, loads `.env`, and keeps the SQLite
ledger in a named volume so local session history survives container restarts:

```bash
docker compose up --build
```

## Deploy to Google Cloud Run

Cloud Run builds on the same image. It provides the public HTTPS URL and injects
`PORT=8080` automatically, so do not hardcode a port.

1. Set your project and enable the required APIs:

   ```bash
   gcloud config set project PROJECT_ID
   gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com
   ```

2. Build and push the image. Either use Cloud Build directly:

   ```bash
   gcloud builds submit --tag gcr.io/PROJECT_ID/superset-security-check
   ```

   Or push to Artifact Registry:

   ```bash
   gcloud artifacts repositories create webhooks --repository-format=docker --location=us-central1
   gcloud builds submit --tag us-central1-docker.pkg.dev/PROJECT_ID/webhooks/superset-security-check
   ```

3. Store `WEBHOOK_SECRET` and `DEVIN_API_KEY` in Secret Manager rather than as
   plaintext service configuration, and grant the service account access:

   ```bash
   printf '%s' 'your-github-webhook-secret' | gcloud secrets create WEBHOOK_SECRET --data-file=-
   printf '%s' 'your-devin-api-key' | gcloud secrets create DEVIN_API_KEY --data-file=-
   for s in WEBHOOK_SECRET DEVIN_API_KEY; do
     gcloud secrets add-iam-policy-binding "$s" \
       --member "serviceAccount:PROJECT_NUMBER-compute@developer.gserviceaccount.com" \
       --role roles/secretmanager.secretAccessor
   done
   ```

4. Deploy the service, mounting the secrets and passing only non-sensitive
   values as env vars:

   ```bash
   gcloud run deploy superset-security-check \
     --image gcr.io/PROJECT_ID/superset-security-check \
     --region us-central1 \
     --platform managed \
     --allow-unauthenticated \
     --set-secrets WEBHOOK_SECRET=WEBHOOK_SECRET:latest,DEVIN_API_KEY=DEVIN_API_KEY:latest \
     --set-env-vars DEVIN_ORG_ID=your-devin-organization-id,DEVIN_PLAYBOOK_ID=your-devin-playbook-id,DEVIN_API_BASE_URL=https://api.devin.ai/v3
   ```

   The command prints the service URL, for example
   `https://superset-security-check-xxxxxxx-uc.a.run.app`. Use that host when
   configuring the GitHub webhook.

   Passing `WEBHOOK_SECRET` or `DEVIN_API_KEY` through `--set-env-vars` instead
   would store them as plaintext service configuration readable by anyone with
   `run.services.get`, and leave them in shell history and CI logs.

### Session ledger persistence

The session ledger is a SQLite file at `SESSION_DB_PATH` (default `sessions.db`),
which lives on the container's ephemeral filesystem. On Cloud Run it is lost when
an instance is recycled and is not shared between instances, so the dashboard and
`/metrics` will only reflect sessions recorded by the instance that served them.
Either accept that ephemerality (the dashboard stays useful for recent activity)
or point the service at a persistent store, for example a Cloud Storage FUSE
volume mount for the SQLite file, or a managed database if you adapt
`analytics.py`. Locally, `docker compose` already mounts a volume for it.

## GitHub setup: connect a target repository to the webhook

1. Choose the target GitHub repository whose pushes should trigger Devin sessions.
2. Generate a strong webhook secret and set it as `WEBHOOK_SECRET` for the
   service. It must match exactly what GitHub is configured to send:

   ```bash
   openssl rand -hex 32
   ```

3. Deploy the service so it has a public HTTPS URL — either Cloud Run (see above)
   or Docker locally plus a tunnel (`ngrok http 5000`).
4. In the target repository, go to Settings → Webhooks → Add webhook.
5. Set Payload URL to `https://<your-host>/webhook/commit`, Content type to
   `application/json`, and Secret to the same `WEBHOOK_SECRET` value.
6. Under "Which events would you like to trigger this webhook?", choose
   "Just the push event" — the handler processes push payloads at
   `/webhook/commit`.
7. Save the webhook. GitHub immediately sends a ping; check the "Recent
   Deliveries" tab for the response, and confirm the service logs and
   `https://<your-host>/dashboard` are reachable.
8. Push a commit to the target repository and confirm a Devin session is created
   and shows up on the dashboard.

## Dashboard usage

The webhook service exposes a real-time dashboard for monitoring Devin sessions:

**Dashboard endpoint:** `http://localhost:5000/dashboard`

The dashboard displays:
- **Overview metrics:** Total sessions, active count, completed, failed, and success rate
- **Repository breakdown:** Per-repository session counts and status distribution
- **Auto-refresh:** The dashboard automatically polls active sessions every 15 seconds and reloads
- **Active session tracking:** Lists all sessions currently in "created" or "running" status

**Metrics endpoint (JSON):** `http://localhost:5000/metrics`

Returns aggregated session metrics and list of active session IDs for programmatic access.

**Poll session status:** `http://localhost:5000/poll-status/<session_id>`

Fetches the current status of a specific Devin session from the API and updates the local ledger.

## Example curl test

```bash
PAYLOAD='{"ref":"refs/heads/main","repository":{"full_name":"acme/demo"},"head_commit":{"id":"abc123","message":"feat: add security check"},"commits":[{"id":"abc123","message":"feat: add security check"},{"id":"def456","message":"fix: update branch logic"}]}'
SIG=$(printf '%s' "$PAYLOAD" | openssl dgst -sha256 -hmac "$WEBHOOK_SECRET" -binary | xxd -p -c 256)

curl -X POST http://localhost:5000/webhook/commit \
  -H "Content-Type: application/json" \
  -H "X-Hub-Signature-256: sha256=$SIG" \
  --data "$PAYLOAD"
```

## Demo deck and narration script

`scripts/generate_deck.py` holds the content for the walkthrough video deck (What / How /
Why / When) and is the single source for both the slides and the narration in
[docs/superset-security-check-script.md](docs/superset-security-check-script.md). Edit the
`DECK` definition in the script, then regenerate:

```bash
pip install -r requirements-deck.txt

python scripts/generate_deck.py --script-only                       # narration script only
python scripts/generate_deck.py --pptx build/deck.pptx              # .pptx to import into Slides
python scripts/generate_deck.py --share-with you@example.com        # native Google Slides file
```

The native Google Slides path needs credentials with the `presentations` and `drive`
scopes: set `GOOGLE_APPLICATION_CREDENTIALS` or `GOOGLE_SERVICE_ACCOUNT_JSON` to a
service-account JSON, or `GOOGLE_OAUTH_CLIENT_SECRETS` / `GOOGLE_OAUTH_TOKEN` for OAuth.
Every slide carries its narration in the speaker notes with a timing hint.

## Notes

This is intentionally lightweight and can be adapted for GitHub, GitLab, Bitbucket, or any custom commit webhook provider.
