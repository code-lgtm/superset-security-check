# Professional Dashboard Template
# This is a helper to generate the new dashboard HTML

def generate_dashboard_html(metrics):
    """Generate professional dashboard with Chart.js visualizations."""
    
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
    
    # Generate JavaScript for charts
    chart_js = f"""
    const activeSessions = {repr(metrics['active_sessions'])};
    const statusLabels = {repr(status_labels)};
    const statusData = {repr(status_data)};
    const statusColors = {repr(status_chart_colors)};
    const repoNames = {repr(repo_names)};
    const repoSuccessRates = {repr(repo_success_rates)};
    const hourlyLabels = {repr(hourly_labels)};
    const hourlyData = {repr(hourly_data)};
    
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
    """
    
    html = f"""<!DOCTYPE html>
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
          <div class="metric-subtext">Success Rate: {metrics['success_rate']*100:.1f}%</div>
        </div>
        <div class="metric-card">
          <div class="metric-label">Total Sessions</div>
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
      {chart_js}
    </script>
  </body>
</html>
"""
    return html
