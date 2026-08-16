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
    # Mark completion time when status transitions to completed/failed
    if not completed_at and status in {"completed", "failed"}:
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
    
    for row in rows:
        session_id, repository, _, _, _, status, _, created_at, completed_at = row
        by_status[status] = by_status.get(status, 0) + 1
        if status in {"created", "running"}:
            active_sessions.append(session_id)

        repo_entry = by_repository.setdefault(
            repository,
            {"total": 0, "active": 0, "completed": 0, "failed": 0, "success_rate": 0},
        )
        repo_entry["total"] += 1
        if status in {"created", "running"}:
            repo_entry["active"] += 1
        if status == "completed":
            repo_entry["completed"] += 1
        if status == "failed":
            repo_entry["failed"] += 1
        
        # Calculate per-repo success rate
        if repo_entry["total"] > 0:
            repo_entry["success_rate"] = repo_entry["completed"] / repo_entry["total"]
        
        # Calculate session duration
        if created_at and completed_at and status in {"completed", "failed"}:
            try:
                # Handle both timezone-aware and naive datetimes
                created = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                completed_dt = datetime.fromisoformat(completed_at.replace('Z', '+00:00'))
                
                # If created is naive, make it aware UTC
                if created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)
                if completed_dt.tzinfo is None:
                    completed_dt = completed_dt.replace(tzinfo=timezone.utc)
                    
                duration_seconds = (completed_dt - created).total_seconds()
                if duration_seconds >= 0:
                    durations.append(duration_seconds)
            except (ValueError, AttributeError, TypeError):
                pass
        
        # Track hourly throughput
        if created_at:
            try:
                hour_key = created_at[:13]  # YYYY-MM-DDTHH
                hourly_throughput[hour_key] = hourly_throughput.get(hour_key, 0) + 1
            except (ValueError, IndexError):
                pass

    active = by_status.get("created", 0) + by_status.get("running", 0)
    completed = by_status.get("completed", 0)
    failed = by_status.get("failed", 0)
    success_rate = (completed / total) if total else 0.0
    
    # Calculate failure rate trend (last 24h)
    cutoff_24h = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    failed_24h = sum(1 for row in rows if row[5] == "failed" and row[7] >= cutoff_24h)
    total_24h = sum(1 for row in rows if row[7] >= cutoff_24h)
    failure_rate_24h = (failed_24h / total_24h) if total_24h else 0.0
    
    # Throughput metrics
    cutoff_24h = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    cutoff_7d = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    throughput_24h = sum(1 for row in rows if row[7] >= cutoff_24h)
    throughput_last_7_days = sum(1 for row in rows if row[7] >= cutoff_7d)
    
    # Average duration
    avg_duration = sum(durations) / len(durations) if durations else 0

    return {
        "total": total,
        "active": active,
        "completed": completed,
        "failed": failed,
        "success_rate": success_rate,
        "failure_rate_24h": failure_rate_24h,
        "by_status": by_status,
        "by_repository": by_repository,
        "active_sessions": active_sessions,
        "throughput_24h": throughput_24h,
        "throughput_last_7_days": throughput_last_7_days,
        "avg_duration_seconds": avg_duration,
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
    print(status)
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
    
    # Prepare data for charts
    hourly_labels = [h[0] for h in metrics["hourly_throughput"]]
    hourly_data = [h[1] for h in metrics["hourly_throughput"]]
    
    status_labels = list(metrics["by_status"].keys())
    status_data = list(metrics["by_status"].values())
    status_colors = {
        "completed": "#28a745", 
        "failed": "#dc3545", 
        "created": "#007bff", 
        "running": "#ffc107"
    }
    status_chart_colors = [status_colors.get(s, "#6c757d") for s in status_labels]
    
    # Repository performance sorted by success rate
    repo_perf = sorted(
        metrics["by_repository"].items(),
        key=lambda x: x[1]["success_rate"],
        reverse=True
    )
    repo_names = [r[0] for r in repo_perf]
    repo_success_rates = [r[1]["success_rate"] * 100 for r in repo_perf]
    
    repo_detail_rows = ""
    for name, data in repo_perf:
        success_rate = data["success_rate"] * 100
        if success_rate > 80:
            color = "green"
        elif success_rate > 50:
            color = "orange"
        else:
            color = "red"
        
        repo_detail_rows += (
            f"<tr style='border-bottom: 1px solid #e0e0e0;'>"
            f"<td style='padding: 12px; font-weight: 500;'>{name}</td>"
            f"<td style='padding: 12px; text-align: center;'>{data['total']}</td>"
            f"<td style='padding: 12px; text-align: center; color: #007bff;'><strong>{data['active']}</strong></td>"
            f"<td style='padding: 12px; text-align: center; color: #28a745;'>{data['completed']}</td>"
            f"<td style='padding: 12px; text-align: center; color: #dc3545;'>{data['failed']}</td>"
            f"<td style='padding: 12px; text-align: center;'>"
            f"<span style='background: {color}; color: white; padding: 4px 8px; border-radius: 4px;'>{success_rate:.1f}%</span>"
            f"</td></tr>"
        )
    
    # Health status indicator
    success_rate = metrics["success_rate"]
    if success_rate > 0.8:
        health_status = "🟢 Healthy"
        health_color_rgb = "40, 167, 69"
    elif success_rate > 0.5:
        health_status = "🟡 Warning"
        health_color_rgb = "255, 193, 7"
    else:
        health_status = "🔴 Critical"
        health_color_rgb = "220, 53, 69"
    
    # Format duration
    avg_duration = metrics['avg_duration_seconds']
    if avg_duration > 0:
        duration_str = f"{int(avg_duration)}s"
    else:
        duration_str = "N/A"
    
    # Generate JavaScript for charts - using literal string to avoid brace issues
    chart_js_data = f"""const activeSessions = {repr(metrics['active_sessions'])};
    const statusLabels = {repr(status_labels)};
    const statusData = {repr(status_data)};
    const statusColors = {repr(status_chart_colors)};
    const repoNames = {repr(repo_names)};
    const repoSuccessRates = {repr(repo_success_rates)};
    const hourlyLabels = {repr(hourly_labels)};
    const hourlyData = {repr(hourly_data)};
    """
    
    return f"""<!DOCTYPE html>
<html>
  <head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Devin Session Dashboard</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
      * {{ margin: 0; padding: 0; box-sizing: border-box; }}
      body {{
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
        background: #f5f7fa;
        color: #2c3e50;
      }}
      .header {{
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        padding: 32px 20px;
        margin-bottom: 32px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.1);
      }}
      .header h1 {{ font-size: 28px; margin-bottom: 8px; }}
      .header p {{ font-size: 14px; opacity: 0.9; }}
      .container {{ max-width: 1400px; margin: 0 auto; padding: 0 20px; }}
      .metrics-grid {{
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
        gap: 16px;
        margin-bottom: 32px;
      }}
      .metric-card {{
        background: white;
        padding: 20px;
        border-radius: 8px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        border-left: 4px solid #667eea;
      }}
      .metric-label {{ font-size: 12px; text-transform: uppercase; color: #7f8c8d; margin-bottom: 8px; }}
      .metric-value {{ font-size: 32px; font-weight: bold; }}
      .metric-subtext {{ font-size: 12px; color: #95a5a6; margin-top: 4px; }}
      .health-indicator {{
        font-size: 24px; 
        margin-bottom: 8px;
        padding: 12px;
        background: rgba({health_color_rgb}, 0.1);
        border-radius: 4px;
        text-align: center;
      }}
      .charts-grid {{
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(400px, 1fr));
        gap: 24px;
        margin-bottom: 32px;
      }}
      .chart-card {{
        background: white;
        padding: 24px;
        border-radius: 8px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.1);
      }}
      .chart-title {{ font-size: 16px; font-weight: 600; margin-bottom: 16px; }}
      .table-card {{
        background: white;
        border-radius: 8px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        overflow: hidden;
        margin-bottom: 32px;
      }}
      .table-header {{
        background: #f8f9fa;
        padding: 16px 20px;
        border-bottom: 1px solid #e0e0e0;
        font-weight: 600;
        font-size: 14px;
      }}
      table {{
        width: 100%;
        border-collapse: collapse;
      }}
      th, td {{ padding: 12px 20px; text-align: left; }}
      th {{ background: #f8f9fa; border-bottom: 2px solid #e0e0e0; font-weight: 600; }}
      tr:hover {{ background: #f8f9fa; }}
      canvas {{ max-height: 400px; }}
    </style>
  </head>
  <body>
    <div class="header">
      <h1>🚀 Devin Session Dashboard</h1>
      <p>Real-time monitoring and analytics</p>
    </div>
    
    <div class="container">
      <div class="metrics-grid">
        <div class="metric-card">
          <div class="metric-label">System Health</div>
          <div class="health-indicator">{health_status}</div>
          <div class="metric-subtext">Success rate: {metrics['success_rate']*100:.1f}%</div>
        </div>
        <div class="metric-card">
          <div class="metric-label">Total sessions</div>
          <div class="metric-value">{metrics['total']}</div>
          <div class="metric-subtext">Active: {metrics['active']}</div>
        </div>
        <div class="metric-card">
          <div class="metric-label">Completed</div>
          <div class="metric-value" style="color: #28a745;">{metrics['completed']}</div>
          <div class="metric-subtext">Success Rate: {metrics['success_rate']*100:.1f}%</div>
        </div>
        <div class="metric-card">
          <div class="metric-label">Failed</div>
          <div class="metric-value" style="color: #dc3545;">{metrics['failed']}</div>
          <div class="metric-subtext">Failure Rate (24h): {metrics['failure_rate_24h']*100:.1f}%</div>
        </div>
        <div class="metric-card">
          <div class="metric-label">Throughput (24h)</div>
          <div class="metric-value">{metrics['throughput_24h']}</div>
          <div class="metric-subtext">7 days: {metrics['throughput_last_7_days']}</div>
        </div>
        <div class="metric-card">
          <div class="metric-label">Avg Duration</div>
          <div class="metric-value">{duration_str}</div>
          <div class="metric-subtext">Completed sessions</div>
        </div>
      </div>
      
      <div class="charts-grid">
        <div class="chart-card">
          <div class="chart-title">📊 Status Distribution</div>
          <canvas id="statusChart"></canvas>
        </div>
        <div class="chart-card">
          <div class="chart-title">📈 Repository Performance</div>
          <canvas id="repoChart"></canvas>
        </div>
        <div class="chart-card" style="grid-column: 1 / -1;">
          <div class="chart-title">📉 Hourly Throughput</div>
          <canvas id="throughputChart"></canvas>
        </div>
      </div>
      
      <div class="table-card">
        <div class="table-header">Repository Breakdown</div>
        <table>
          <thead>
            <tr>
              <th>Repository</th>
              <th>Total</th>
              <th>Active</th>
              <th>Completed</th>
              <th>Failed</th>
              <th>Success Rate</th>
            </tr>
          </thead>
          <tbody>
            {repo_detail_rows}
          </tbody>
        </table>
      </div>
    </div>
    
    <script>
      {chart_js_data}
      
      // Status Distribution Chart
      new Chart(document.getElementById('statusChart').getContext('2d'), {{
        type: 'doughnut',
        data: {{
          labels: statusLabels,
          datasets: [{{
            data: statusData,
            backgroundColor: statusColors
          }}]
        }},
        options: {{ responsive: true, maintainAspectRatio: true }}
      }});
      
      // Repository Performance Chart
      new Chart(document.getElementById('repoChart').getContext('2d'), {{
        type: 'bar',
        data: {{
          labels: repoNames,
          datasets: [{{
            label: 'Success Rate (%)',
            data: repoSuccessRates,
            backgroundColor: '#007bff'
          }}]
        }},
        options: {{
          indexAxis: 'y',
          responsive: true,
          scales: {{ x: {{ max: 100, beginAtZero: true }} }}
        }}
      }});
      
      // Throughput Chart
      new Chart(document.getElementById('throughputChart').getContext('2d'), {{
        type: 'line',
        data: {{
          labels: hourlyLabels,
          datasets: [{{
            label: 'Sessions/Hour',
            data: hourlyData,
            borderColor: '#28a745',
            backgroundColor: 'rgba(40, 167, 69, 0.1)',
            tension: 0.3
          }}]
        }},
        options: {{ responsive: true, scales: {{ y: {{ beginAtZero: true }} }} }}
      }});
      
      function refreshData() {{
        fetch('/metrics')
          .then(response => response.json())
          .then(data => {{
            if (data.active_sessions && data.active_sessions.length) {{
              data.active_sessions.forEach(sessionId => {{
                fetch('/poll-status/' + sessionId).catch(() => {{}});
              }});
            }}
            setTimeout(() => window.location.reload(), 1000);
          }})
          .catch(() => {{}});
      }}
      setInterval(refreshData, 15000);
    </script>
  </body>
</html>
"""
