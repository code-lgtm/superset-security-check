import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict

import requests

from dashboard_template import generate_dashboard_html

# Devin Sessions API status vocabulary
TERMINAL_STATUSES = {"finished", "expired", "suspended"}
ACTIVE_STATUSES = {"created", "running", "blocked"}
STALE_STATUSES = {"expired", "suspended"}


def get_db_connection(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT UNIQUE,
            repository TEXT,
            branch TEXT,
            head_commit TEXT,
            commit_count INTEGER,
            status TEXT,
            result TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            completed_at TEXT
        )
        """
    )
    # Migration: add completed_at column if it doesn't exist
    try:
        conn.execute("ALTER TABLE sessions ADD COLUMN completed_at TEXT")
        conn.commit()
    except sqlite3.OperationalError:
        pass  # Column already exists
    return conn


def record_session(
    db_path: str | Path,
    session_id: str,
    repository: str,
    branch: str,
    head_commit: str,
    commit_count: int,
    status: str,
    result: str | None = None,
    completed_at: str | None = None,
) -> None:
    conn = get_db_connection(db_path)
    # Mark completion time when the session reaches a terminal API status
    if not completed_at and status in TERMINAL_STATUSES:
        completed_at = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        INSERT OR REPLACE INTO sessions (
            session_id, repository, branch, head_commit, commit_count, status, result, completed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            session_id,
            repository,
            branch,
            head_commit,
            commit_count,
            status,
            result,
            completed_at,
        ),
    )
    conn.commit()
    conn.close()


def _safe_iso(dt_value: str) -> str:
    if not dt_value:
        return ""
    return dt_value


def _parse_utc(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError, TypeError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _percentile(sorted_values: list[float], fraction: float) -> float:
    if not sorted_values:
        return 0.0
    index = round(fraction * (len(sorted_values) - 1))
    return sorted_values[index]


def _median(sorted_values: list[float]) -> float:
    if not sorted_values:
        return 0.0
    mid = len(sorted_values) // 2
    if len(sorted_values) % 2:
        return sorted_values[mid]
    return (sorted_values[mid - 1] + sorted_values[mid]) / 2


def get_session_metrics(db_path: str | Path) -> Dict[str, Any]:
    conn = get_db_connection(db_path)
    rows = conn.execute(
        """
        SELECT session_id, repository, branch, head_commit, commit_count, status, result, created_at, completed_at
        FROM sessions
        ORDER BY created_at DESC
        """
    ).fetchall()
    conn.close()

    total = len(rows)
    by_status = {}
    by_repository = {}
    active_sessions = []
    durations = []
    hourly_throughput = {}
    branches = set()
    created_timestamps = []
    total_commits = 0
    creation_success = 0
    creation_error = 0

    for row in rows:
        session_id, repository, branch, _, commit_count, status, result, created_at, completed_at = row
        by_status[status] = by_status.get(status, 0) + 1
        if status in ACTIVE_STATUSES:
            active_sessions.append(session_id)

        branches.add((repository, branch))
        total_commits += commit_count or 0

        # `result` records whether the webhook managed to create the session,
        # which is the only success/failure signal the API flow provides.
        if result == "success":
            creation_success += 1
        elif result == "error":
            creation_error += 1

        repo_entry = by_repository.setdefault(
            repository,
            {"total": 0, "active": 0, "blocked": 0, "finished": 0, "branches": 0, "_branches": set()},
        )
        repo_entry["total"] += 1
        if status in ACTIVE_STATUSES:
            repo_entry["active"] += 1
        if status == "blocked":
            repo_entry["blocked"] += 1
        if status == "finished":
            repo_entry["finished"] += 1
        repo_entry["_branches"].add(branch)
        repo_entry["branches"] = len(repo_entry["_branches"])

        # Calculate session duration
        created = _parse_utc(created_at)
        if created:
            created_timestamps.append(created)

        if created and status in TERMINAL_STATUSES:
            completed_dt = _parse_utc(completed_at)
            if completed_dt:
                duration_seconds = (completed_dt - created).total_seconds()
                if duration_seconds >= 0:
                    durations.append(duration_seconds)

        # Track hourly throughput
        if created_at:
            hour_key = created_at[:13]  # YYYY-MM-DDTHH
            hourly_throughput[hour_key] = hourly_throughput.get(hour_key, 0) + 1

    for repo_entry in by_repository.values():
        repo_entry.pop("_branches", None)

    active = sum(by_status.get(status, 0) for status in ACTIVE_STATUSES)
    blocked = by_status.get("blocked", 0)
    finished = by_status.get("finished", 0)
    stale = sum(by_status.get(status, 0) for status in STALE_STATUSES)

    # Session creation success rate: did the webhook manage to create the session?
    creation_attempts = creation_success + creation_error
    creation_success_rate = (creation_success / creation_attempts) if creation_attempts else 0.0

    # Throughput metrics, compared as datetimes because SQLite's CURRENT_TIMESTAMP
    # format ("YYYY-MM-DD HH:MM:SS") does not sort against ISO 8601 strings.
    now = datetime.now(timezone.utc)
    cutoff_24h = now - timedelta(hours=24)
    cutoff_7d = now - timedelta(days=7)
    throughput_24h = sum(1 for created in created_timestamps if created >= cutoff_24h)
    throughput_last_7_days = sum(1 for created in created_timestamps if created >= cutoff_7d)

    # Duration distribution over terminal sessions
    sorted_durations = sorted(durations)
    avg_duration = sum(durations) / len(durations) if durations else 0

    return {
        "total": total,
        "active": active,
        "blocked": blocked,
        "finished": finished,
        "stale": stale,
        "creation_success_rate": creation_success_rate,
        "creation_attempts": creation_attempts,
        "by_status": by_status,
        "by_repository": by_repository,
        "active_sessions": active_sessions,
        "distinct_repositories": len(by_repository),
        "distinct_branches": len(branches),
        "throughput_24h": throughput_24h,
        "throughput_last_7_days": throughput_last_7_days,
        "avg_duration_seconds": avg_duration,
        "median_duration_seconds": _median(sorted_durations),
        "p90_duration_seconds": _percentile(sorted_durations, 0.9),
        "total_commits": total_commits,
        "avg_commits_per_session": (total_commits / total) if total else 0.0,
        "hourly_throughput": sorted(hourly_throughput.items()),
    }


def poll_devin_session_status(db_path: str | Path, session_id: str) -> Dict[str, Any]:
    api_key = os.environ.get("DEVIN_API_KEY", "")
    org_id = os.environ.get("DEVIN_ORG_ID", "")
    base_url = os.environ.get("DEVIN_API_BASE_URL", "https://api.devin.ai/v3")

    if not api_key or not org_id:
        raise RuntimeError("DEVIN_API_KEY and DEVIN_ORG_ID must be configured")

    url = f"{base_url}/organizations/{org_id}/sessions/{session_id}"
    try:
        response = requests.get(
            url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
    except requests.exceptions.RequestException as e:
        print(f"[POLL] Error fetching session {session_id}: {e}")
        return {"status": "unknown", "result": "error", "error": str(e)}

    print(f"[POLL] Session {session_id}: API Response = {payload}")
    
    status = str(payload.get("status", "unknown")).lower()
    result = payload.get("result") or payload.get("state")

    conn = get_db_connection(db_path)
    row = conn.execute(
        "SELECT repository, branch, head_commit, commit_count, result FROM sessions WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    if row is None:
        repository = "unknown"
        branch = "unknown"
        head_commit = "unknown"
        commit_count = 0
    else:
        repository, branch, head_commit, commit_count, stored_result = row
        # `result` tracks session creation, so keep it when the API reports none.
        result = result or stored_result

    record_session(
        db_path,
        session_id=session_id,
        repository=repository,
        branch=branch,
        head_commit=head_commit,
        commit_count=commit_count,
        status=status,
        result=result,
    )
    conn.close()
    return {"status": status, "result": result}


def render_dashboard(db_path: str | Path) -> str:
    return generate_dashboard_html(get_session_metrics(db_path))
