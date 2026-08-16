# Dashboard and metrics

Both views read the same SQLite ledger at `SESSION_DB_PATH` (default `sessions.db`) and the
same aggregation function, `get_session_metrics` in `analytics.py`.

## `/dashboard` (HTML)

`GET /dashboard` returns the server-rendered page produced by `render_dashboard`, which
delegates to `generate_dashboard_html` in `dashboard_template.py`:

- **Metric cards** — session health (🟢 < 20% of sessions blocked or stale, 🟡 < 50%, 🔴
  otherwise), total sessions with active count, session creation success rate, finished
  (terminal) count, blocked (awaiting human input), stale/expired, 24-hour throughput with
  the 7-day figure, adoption (distinct repositories and branches), average commits per
  session, and duration (mean with median and p90).
- **Charts** (Chart.js from a CDN) — a status distribution doughnut, a horizontal bar chart
  of session volume per repository, and a line chart of hourly throughput.
- **Repository breakdown table** — total, active, blocked, finished, and distinct branches
  per repository, sorted by session volume.
- **Auto-refresh** — every 15 seconds the page fetches `/metrics`, calls
  `/poll-status/<session_id>` for each id in `active_sessions`, then reloads itself after a
  one-second delay so the refreshed statuses are shown.

## `/metrics` (JSON)

`GET /metrics` returns the `get_session_metrics` dict:

| Field | Meaning |
| --- | --- |
| `total` | Number of session rows in the ledger. |
| `active` | Sessions in a non-terminal status (`created`, `running`, `blocked`). |
| `blocked` | Sessions awaiting human input. |
| `finished` | Sessions with the terminal status `finished`. |
| `stale` | Sessions with status `expired` or `suspended`. |
| `creation_success_rate` | `result == "success"` over all rows with a `result`; whether the webhook created the session, not a task verdict. |
| `creation_attempts` | Rows with a `result` of `success` or `error`. |
| `by_status` | Count per raw status string. |
| `by_repository` | Per repository: `total`, `active`, `blocked`, `finished`, `branches`. |
| `active_sessions` | Session ids in a non-terminal status; the dashboard polls these. |
| `distinct_repositories` | Number of repositories seen in the ledger. |
| `distinct_branches` | Number of distinct repository/branch pairs. |
| `throughput_24h` | Sessions created in the last 24 hours. |
| `throughput_last_7_days` | Sessions created in the last 7 days. |
| `avg_duration_seconds` | Mean `completed_at - created_at` over terminal sessions with parseable, non-negative durations; `0` when none. |
| `median_duration_seconds` | Median of the same durations. |
| `p90_duration_seconds` | 90th percentile of the same durations. |
| `total_commits` | Sum of the `commit_count` column. |
| `avg_commits_per_session` | `total_commits / total`, `0.0` when empty. |
| `hourly_throughput` | Sorted `[hour, count]` pairs keyed by the `YYYY-MM-DDTHH` prefix of `created_at`. |

Rates are fractions, not percentages — the dashboard multiplies them by 100 for display.

## `/poll-status/<session_id>`

`GET` or `POST /poll-status/<session_id>` calls `poll_devin_session_status`, which fetches
`<DEVIN_API_BASE_URL>/organizations/<DEVIN_ORG_ID>/sessions/<session_id>`, normalizes the
status to lowercase, takes `result` from the API's `result` or `state` field (keeping the
stored creation `result` when the API reports none), upserts the row via `record_session`
(which stamps `completed_at` on the terminal statuses `finished`, `expired`, `suspended`),
and responds with
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
