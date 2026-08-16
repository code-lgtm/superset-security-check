# Documentation

`superset-security-check` is a small Flask service that turns Git push events into Devin
sessions. It receives a push webhook at `/webhook/commit`, verifies the HMAC SHA-256
signature against the shared `WEBHOOK_SECRET`, parses the payload into a normalized commit
summary (repository, branch, head commit, commit count, commit messages), creates one Devin
session per push through the Devin API, and records that session in a SQLite ledger. The
ledger is aggregated into metrics that are exposed as JSON at `/metrics` and rendered as an
auto-refreshing HTML view at `/dashboard`, with `/poll-status/<session_id>` refreshing a
single session's status from the Devin API.

## Contents

- [Architecture](architecture.md) — modules, routes, and the end-to-end request flow.
- [Configuration](configuration.md) — environment variables and their defaults.
- [Dashboard and metrics](dashboard.md) — `/dashboard`, `/metrics`, and status polling.

## Quick links

- Root [README](../README.md) for install and run instructions.
- [.env.example](../.env.example) for the environment variable template. Never commit a real
  `.env`; it is git-ignored.
