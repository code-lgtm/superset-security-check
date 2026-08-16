# Dashboard and metrics

Both views read the same SQLite ledger at `SESSION_DB_PATH` (default `sessions.db`) and the
same aggregation function, `get_session_metrics` in `analytics.py`.

## `/dashboard` (HTML)

`GET /dashboard` returns the server-rendered page produced by `render_dashboard`:

- **Metric cards** — system health (🟢 > 80% success, 🟡 > 50%, 🔴 otherwise), total
  sessions with active count, completed with success rate, failed with the 24-hour failure
  rate, 24-hour throughput with the 7-day figure, and average duration (`N/A` when no
  completed sessions have a usable duration).
- **Charts** (Chart.js from a CDN) — a status distribution doughnut, a horizontal bar chart
  of per-repository success rate, and a line chart of hourly throughput.
- **Repository breakdown table** — total, active, completed, failed, and success rate per
  repository, sorted by success rate, with the rate badge coloured green/orange/red at the
  80%/50% thresholds.
- **Auto-refresh** — every 15 seconds the page fetches `/metrics`, calls
  `/poll-status/<session_id>` for each id in `active_sessions`, then reloads itself after a
  one-second delay so the refreshed statuses are shown.

## `/metrics` (JSON)

`GET /metrics` returns the `get_session_metrics` dict:

| Field | Meaning |
| --- | --- |
| `total` | Number of session rows in the ledger. |
| `active` | Sessions with status `created` or `running`. |
| `completed` | Sessions with status `completed`. |
| `failed` | Sessions with status `failed`. |
| `success_rate` | `completed / total` as a fraction (0.0–1.0), `0.0` when empty. |
| `failure_rate_24h` | Failed sessions created in the last 24 hours divided by all sessions created in that window. |
| `by_status` | Count per raw status string. |
| `by_repository` | Per repository: `total`, `active`, `completed`, `failed`, `success_rate`. |
| `active_sessions` | Session ids currently `created` or `running`; the dashboard polls these. |
| `throughput_24h` | Sessions created in the last 24 hours. |
| `throughput_last_7_days` | Sessions created in the last 7 days. |
| `avg_duration_seconds` | Mean `completed_at - created_at` over terminal sessions with parseable, non-negative durations; `0` when none. |
| `hourly_throughput` | Sorted `[hour, count]` pairs keyed by the `YYYY-MM-DDTHH` prefix of `created_at`. |

Rates are fractions, not percentages — the dashboard multiplies them by 100 for display.

## `/poll-status/<session_id>`

`GET` or `POST /poll-status/<session_id>` calls `poll_devin_session_status`, which fetches
`<DEVIN_API_BASE_URL>/organizations/<DEVIN_ORG_ID>/sessions/<session_id>`, normalizes the
status to lowercase, derives `result` from the API's `result` or `state` field (defaulting to
`success` for `completed` and `error` for `failed`), upserts the row via `record_session`
(which stamps `completed_at` on terminal statuses), and responds with
`{"status": ..., "result": ...}`.

Failure modes: a `requests` error yields `{"status": "unknown", "result": "error", "error":
...}` with HTTP 200; any other exception is caught by the route and returned as
`{"error": ...}` with HTTP 500. Polling requires `DEVIN_API_KEY` and `DEVIN_ORG_ID`. Note
that polling a session id that is not in the ledger inserts it with `unknown` repository,
branch, and head commit.

## `/debug/session/<session_id>`

`GET /debug/session/<session_id>` returns the raw Devin API response (plus the request URL,
HTTP status code, and a UTC timestamp) without touching the ledger. Useful when a session's
status is not advancing as expected.
