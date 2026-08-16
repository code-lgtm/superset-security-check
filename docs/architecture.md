# Architecture

The service is four Python modules plus a test suite. There is no framework beyond Flask,
`requests`, and the standard library's `sqlite3`.

## Components

### `app.py` — shared helpers

- `verify_signature(payload, signature, secret)` — computes `hmac.new(secret, payload,
  sha256).hexdigest()` and compares it to the supplied signature with
  `hmac.compare_digest`. Returns `False` when either the signature or the secret is empty.
  The caller is responsible for stripping the `sha256=` prefix used by GitHub.
- `extract_commits(event)` — normalizes a push payload into a dict with `repository`
  (`repository.full_name`, or `"unknown"`), `branch` (`ref` with a leading `refs/heads/`
  removed), `head_commit` (`head_commit.id`), `commit_count` (length of `commits`), and
  `messages` (the message of each entry in `commits`).

### `webhook.py` — Flask app, routes, and Devin API integration

Routes:

| Route | Methods | Purpose |
| --- | --- | --- |
| `/webhook/commit` | POST | Verify the signature, parse the push, create and record a Devin session. |
| `/health` | GET | Liveness probe; returns `{"status": "ok"}`. |
| `/metrics` | GET | Aggregated session metrics as JSON. |
| `/dashboard` | GET | Server-rendered HTML dashboard. |
| `/poll-status/<session_id>` | GET, POST | Fetch one session's status from the Devin API and update the ledger. |
| `/debug/session/<session_id>` | GET | Raw Devin API response for a session, for debugging polling issues. |

Devin integration:

- `build_devin_session_payload(summary)` — builds the session `name`
  (`Webhook commit - <repository>:<branch>`) and a `prompt` listing the repository, branch,
  and commit messages. `playbook_id` is included only when `DEVIN_PLAYBOOK_ID` is set.
- `create_devin_session(summary)` — POSTs that payload to
  `<DEVIN_API_BASE_URL>/organizations/<DEVIN_ORG_ID>/sessions` with a bearer token and a
  30-second timeout, raising `RuntimeError` when `DEVIN_API_KEY` or `DEVIN_ORG_ID` is
  missing and raising for non-2xx responses.

The webhook handler is deliberately fault-tolerant: if session creation fails it still
records a row, using a synthetic `webhook-<head_commit>` session id with status `failed`,
and returns HTTP 200 with the error under the `devin` key. The `result` column (`success` /
`error`) records whether *session creation* succeeded, not any task-level verdict — the
Sessions API does not report one. Only signature verification
failures abort the request (HTTP 401).

### `analytics.py` — persistence, metrics, polling, rendering

- `get_db_connection(db_path)` — opens the SQLite database and creates the `sessions` table
  if needed (`session_id` unique, `repository`, `branch`, `head_commit`, `commit_count`,
  `status`, `result`, `created_at`, `completed_at`). It also performs an idempotent
  `ALTER TABLE ... ADD COLUMN completed_at` migration for older databases.
- `record_session(...)` — upserts a session row (`INSERT OR REPLACE` on `session_id`) and
  stamps `completed_at` with the current UTC time when the status is one of the terminal API
  statuses in `TERMINAL_STATUSES` (`finished`, `expired`, `suspended`).
- `get_session_metrics(db_path)` — reads every row and aggregates totals, per-status and
  per-repository breakdowns, active/blocked/finished/stale counts, the session creation
  success rate, adoption (distinct repositories and branches), throughput windows, duration
  mean/median/p90, commits per session, and hourly throughput. See
  [dashboard.md](dashboard.md) for the field list.
- `poll_devin_session_status(db_path, session_id)` — GETs
  `<DEVIN_API_BASE_URL>/organizations/<DEVIN_ORG_ID>/sessions/<session_id>`, lowercases the
  returned status, takes `result` from `result`/`state` (falling back to the stored creation
  `result`), and writes the update back through
  `record_session`. Request failures return `{"status": "unknown", "result": "error",
  "error": ...}` instead of raising.
- `render_dashboard(db_path)` — thin wrapper that passes the metrics to
  `generate_dashboard_html`.

### `dashboard_template.py` — dashboard rendering

Holds `generate_dashboard_html(metrics)`, the single source of the dashboard markup: metric
cards, a Chart.js status doughnut, repository session-volume bars, an hourly throughput line
chart, a repository breakdown table, and the auto-refresh script.

### `tests/test_webhook.py`

Regression tests for signature verification, payload parsing, and Devin payload
generation. Run them with `pytest` from the repository root (`pytest.ini` sets
`pythonpath = .`).

## Request flow

```
POST /webhook/commit
  -> verify_signature(body, X-Hub-Signature-256, WEBHOOK_SECRET)   # 401 on mismatch
  -> extract_commits(json_body)                                    # repo, branch, commits
  -> build_devin_session_payload + create_devin_session             # Devin API
  -> record_session(SESSION_DB_PATH, ...)                          # SQLite ledger
  -> GET /dashboard | /metrics                                     # aggregated view
       -> /poll-status/<session_id> refreshes active sessions
```
