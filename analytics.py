import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict

import requests


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
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
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
) -> None:
    conn = get_db_connection(db_path)
    conn.execute(
        """
        INSERT OR REPLACE INTO sessions (
            session_id, repository, branch, head_commit, commit_count, status, result
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            session_id,
            repository,
            branch,
            head_commit,
            commit_count,
            status,
            result,
        ),
    )
    conn.commit()
    conn.close()


def _safe_iso(dt_value: str) -> str:
    if not dt_value:
        return ""
    return dt_value


def get_session_metrics(db_path: str | Path) -> Dict[str, Any]:
    conn = get_db_connection(db_path)
    rows = conn.execute(
        """
        SELECT session_id, repository, branch, head_commit, commit_count, status, result, created_at
        FROM sessions
        ORDER BY created_at DESC
        """
    ).fetchall()
    conn.close()

    total = len(rows)
    by_status = {}
    by_repository = {}
    active_sessions = []
    for row in rows:
        session_id, repository, _, _, _, status, _, _ = row
        by_status[status] = by_status.get(status, 0) + 1
        if status in {"created", "running"}:
            active_sessions.append(session_id)

        repo_entry = by_repository.setdefault(
            repository,
            {"total": 0, "active": 0, "completed": 0, "failed": 0},
        )
        repo_entry["total"] += 1
        if status in {"created", "running"}:
            repo_entry["active"] += 1
        if status == "completed":
            repo_entry["completed"] += 1
        if status == "failed":
            repo_entry["failed"] += 1

    active = by_status.get("created", 0) + by_status.get("running", 0)
    completed = by_status.get("completed", 0)
    failed = by_status.get("failed", 0)
    success_rate = (completed / total) if total else 0.0

    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    throughput_last_7_days = 0
    for row in rows:
        _, _, _, _, _, _, _, created_at = row
        if created_at and created_at >= cutoff:
            throughput_last_7_days += 1

    return {
        "total": total,
        "active": active,
        "completed": completed,
        "failed": failed,
        "success_rate": success_rate,
        "by_status": by_status,
        "by_repository": by_repository,
        "active_sessions": active_sessions,
        "throughput_last_7_days": throughput_last_7_days,
    }


def poll_devin_session_status(db_path: str | Path, session_id: str) -> Dict[str, Any]:
    api_key = os.environ.get("DEVIN_API_KEY", "")
    org_id = os.environ.get("DEVIN_ORG_ID", "")
    base_url = os.environ.get("DEVIN_API_BASE_URL", "https://api.devin.ai/v3")

    if not api_key or not org_id:
        raise RuntimeError("DEVIN_API_KEY and DEVIN_ORG_ID must be configured")

    url = f"{base_url}/organizations/{org_id}/sessions/{session_id}"
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

    status = str(payload.get("status", "unknown")).lower()
    result = payload.get("result") or payload.get("state")
    if status == "completed" and not result:
        result = "success"
    if status == "failed" and not result:
        result = "error"

    conn = get_db_connection(db_path)
    row = conn.execute(
        "SELECT repository, branch, head_commit, commit_count FROM sessions WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    if row is None:
        repository = "unknown"
        branch = "unknown"
        head_commit = "unknown"
        commit_count = 0
    else:
        repository, branch, head_commit, commit_count = row

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
    metrics = get_session_metrics(db_path)

    repo_rows = "".join(
        f"<tr><td>{name}</td><td>{data['total']}</td><td>{data['active']}</td>"
        f"<td>{data['completed']}</td><td>{data['failed']}</td></tr>"
        for name, data in metrics["by_repository"].items()
    )

    script = """
    const activeSessions = ACTIVE_SESSIONS;
    function refreshData() {
      fetch('/metrics')
        .then(response => response.json())
        .then(data => {
          if (data.active_sessions && data.active_sessions.length) {
            data.active_sessions.forEach(sessionId => {
              fetch('/poll-status/' + sessionId).catch(() => {});
            });
          }
          window.location.reload();
        })
        .catch(() => {});
    }
    setInterval(refreshData, 15000);
    """.replace("ACTIVE_SESSIONS", repr(metrics["active_sessions"]))

    return f"""
    <html>
      <head>
        <title>Devin Session Dashboard</title>
        <style>
          body {{ font-family: Arial, sans-serif; margin: 32px; }}
          .card {{ border: 1px solid #ddd; padding: 16px; margin-bottom: 16px; }}
          table {{ border-collapse: collapse; width: 100%; }}
          th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
        </style>
        <script>
          {script}
        </script>
      </head>
      <body>
        <h1>Devin Session Dashboard</h1>
        <div class="card">
          <h2>Overview</h2>
          <p>Total sessions: {metrics['total']}</p>
          <p>Active: {metrics['active']}</p>
          <p>Completed: {metrics['completed']}</p>
          <p>Failed: {metrics['failed']}</p>
          <p>Success rate: {metrics['success_rate']:.2%}</p>
          <p>Throughput (last 7 days): {metrics['throughput_last_7_days']}</p>
        </div>
        <div class="card">
          <h2>Repository breakdown</h2>
          <table>
            <thead>
              <tr>
                <th>Repository</th>
                <th>Total</th>
                <th>Active</th>
                <th>Completed</th>
                <th>Failed</th>
              </tr>
            </thead>
            <tbody>
              {repo_rows}
            </tbody>
          </table>
        </div>
      </body>
    </html>
    """
