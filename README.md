# superset-security-check

This repository is a minimal webhook template for handling commit events from a Git hosting provider.

## What it does

- Receives a POST webhook request at /webhook/commit
- Verifies the HMAC signature using the shared secret
- Parses the push payload and extracts repository, branch, and commit information
- Returns a JSON summary for downstream processing

## Project structure

- app.py: shared validation and payload parsing helpers
- webhook.py: Flask webhook endpoint
- tests/test_webhook.py: regression tests for signature and commit parsing

## Run locally

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
export WEBHOOK_SECRET=change-me
python webhook.py
```

Then send a request like:

```bash
curl -X POST http://localhost:5000/webhook/commit \
  -H "Content-Type: application/json" \
  -H "X-Hub-Signature-256: sha256=$(echo -n '{"ref":"refs/heads/main","repository":{"full_name":"acme/demo"},"commits":[{"message":"feat: add check"}]}' | openssl dgst -sha256 -hmac "change-me" -binary | xxd -p -c 256)" \
  -d '{"ref":"refs/heads/main","repository":{"full_name":"acme/demo"},"commits":[{"message":"feat: add check"}]}'
```

## Notes

This is intentionally small and production-agnostic; it can be adapted for GitHub, GitLab, Bitbucket, or any custom commit webhook provider.
