# Configuration

All configuration is read from environment variables at request time via `os.environ.get`.
Copy [.env.example](../.env.example) to `.env` and fill in your own values; `.env` is
git-ignored, and no real credentials belong in this repository or in these docs.

```bash
cp .env.example .env
```

## Variables

| Variable | Default in code | Used by | Notes |
| --- | --- | --- | --- |
| `WEBHOOK_SECRET` | `change-me` | `/webhook/commit` | Shared secret for HMAC SHA-256 verification of the `X-Hub-Signature-256` header. Must match the secret configured in the Git provider. The built-in default is a placeholder — always set a real secret. |
| `DEVIN_API_KEY` | *(empty)* | `create_devin_session`, `poll_devin_session_status`, `/debug/session/<id>` | Bearer token for the Devin API. Session creation and polling raise `RuntimeError` when it is missing; `/debug/session/<id>` returns HTTP 400. |
| `DEVIN_ORG_ID` | *(empty)* | same as above | Organization id in the API path `/organizations/<org_id>/sessions`. Required alongside the API key. |
| `DEVIN_PLAYBOOK_ID` | *(empty)* | `build_devin_session_payload` | Optional. When set, it is sent as `playbook_id`; when empty the key is omitted. |
| `DEVIN_API_BASE_URL` | `https://api.devin.ai/v3` | `create_devin_session`, `poll_devin_session_status`, `/debug/session/<id>` | Base URL for the Devin API. See the note below. |
| `SESSION_DB_PATH` | `sessions.db` | `/webhook/commit`, `/metrics`, `/dashboard`, `/poll-status/<id>` | Path to the SQLite ledger. The file and the `sessions` table are created on first use. |
| `PORT` | `5000` | `webhook.py` entrypoint | Port for `app.run` when running `python webhook.py` directly. Ignored when served by a WSGI server. |

## Known inconsistency: `DEVIN_API_BASE_URL`

The code defaults to `https://api.devin.ai/v3` in all three call sites
(`create_devin_session` and `poll_devin_session_status` in `analytics.py`/`webhook.py`, and
the `/debug/session/<session_id>` route). `.env.example` also shows `v3`, but the root
[README.md](../README.md) still documents `https://api.devin.ai/v1` in its environment
variables snippet.

This documentation uses `https://api.devin.ai/v3`, matching the code and `.env.example`.
Recommendation: reconcile the root README to the same value (or, if `v1` is the intended
API version, change the defaults in the code and `.env.example` together) so all three
sources agree.
