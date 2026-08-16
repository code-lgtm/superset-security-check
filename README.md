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

## Project structure

- app.py: shared validation and payload parsing helpers
- webhook.py: Flask webhook endpoint and Devin session integration
- tests/test_webhook.py: regression tests for signature, parsing, and Devin payload generation
- .env.example: sample environment variables

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
DEVIN_API_BASE_URL=https://api.devin.ai/v1
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

## Example GitHub push payload

```json
{
  "ref": "refs/heads/main",
  "repository": {
    "full_name": "acme/demo"
  },
  "head_commit": {
    "id": "abc123",
    "message": "feat: add security check"
  },
  "commits": [
    {"id": "abc123", "message": "feat: add security check"},
    {"id": "def456", "message": "fix: update branch logic"}
  ]
}
```

## Example curl test

```bash
PAYLOAD='{"ref":"refs/heads/main","repository":{"full_name":"acme/demo"},"head_commit":{"id":"abc123","message":"feat: add security check"},"commits":[{"id":"abc123","message":"feat: add security check"},{"id":"def456","message":"fix: update branch logic"}]}'
SIG=$(printf '%s' "$PAYLOAD" | openssl dgst -sha256 -hmac "$WEBHOOK_SECRET" -binary | xxd -p -c 256)

curl -X POST http://localhost:5000/webhook/commit \
  -H "Content-Type: application/json" \
  -H "X-Hub-Signature-256: sha256=$SIG" \
  --data "$PAYLOAD"
```

## Notes

This is intentionally lightweight and can be adapted for GitHub, GitLab, Bitbucket, or any custom commit webhook provider.
