import hashlib
import hmac
from datetime import datetime, timedelta, timezone

from analytics import (
    get_db_connection,
    get_session_metrics,
    poll_devin_session_status,
    record_session,
    render_dashboard,
)
from app import extract_commits, verify_signature
from webhook import build_devin_session_payload, create_devin_session


def test_verify_signature_accepts_valid_payload():
    secret = "super-secret"
    payload = b'{"ref":"refs/heads/main"}'
    signature = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()

    assert verify_signature(payload, signature, secret) is True


def test_verify_signature_rejects_invalid_payload():
    payload = b'{"ref":"refs/heads/main"}'

    assert verify_signature(payload, "deadbeef", "super-secret") is False


def test_extract_commits_reads_push_event_details():
    payload = {
        "repository": {"full_name": "acme/demo"},
        "ref": "refs/heads/main",
        "head_commit": {"id": "abc123", "message": "fix auth"},
        "commits": [
            {"id": "111", "message": "first"},
            {"id": "222", "message": "second"},
        ],
    }

    event = extract_commits(payload)

    assert event["repository"] == "acme/demo"
    assert event["branch"] == "main"
    assert event["head_commit"] == "abc123"
    assert event["commit_count"] == 2
    assert event["messages"] == ["first", "second"]


def test_build_devin_session_payload_contains_repo_and_branch(monkeypatch):
    monkeypatch.setenv("DEVIN_PLAYBOOK_ID", "playbook-123")
    summary = {
        "repository": "acme/demo",
        "branch": "main",
        "messages": ["feat: add webhook", "fix: cleanup"],
    }

    payload = build_devin_session_payload(summary)

    assert payload["name"] == "Webhook commit - acme/demo:main"
    assert "acme/demo" in payload["prompt"]
    assert "main" in payload["prompt"]
    assert "feat: add webhook" in payload["prompt"]
    assert payload["playbook_id"] == "playbook-123"


def test_create_devin_session_calls_expected_endpoint(monkeypatch):
    captured = {}

    class DummyResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"id": "session-123"}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        captured["timeout"] = timeout
        return DummyResponse()

    monkeypatch.setenv("DEVIN_API_KEY", "demo-key")
    monkeypatch.setenv("DEVIN_ORG_ID", "demo-org")
    monkeypatch.setattr("webhook.requests.post", fake_post)

    summary = {
        "repository": "acme/demo",
        "branch": "main",
        "messages": ["feat: add webhook"],
    }

    result = create_devin_session(summary)

    assert result == {"id": "session-123"}
    assert captured["url"] == "https://api.devin.ai/v3/organizations/demo-org/sessions"
    assert captured["headers"]["Authorization"] == "Bearer demo-key"
    assert captured["json"]["name"] == "Webhook commit - acme/demo:main"


def test_create_devin_session_uses_v3_default_when_base_url_not_set(monkeypatch):
    captured = {}

    class DummyResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"id": "session-456"}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["url"] = url
        return DummyResponse()

    monkeypatch.delenv("DEVIN_API_BASE_URL", raising=False)
    monkeypatch.setenv("DEVIN_API_KEY", "demo-key")
    monkeypatch.setenv("DEVIN_ORG_ID", "demo-org")
    monkeypatch.setattr("webhook.requests.post", fake_post)

    create_devin_session({"repository": "demo/repo", "branch": "main", "messages": ["x"]})

    assert captured["url"] == "https://api.devin.ai/v3/organizations/demo-org/sessions"


def test_record_session_metrics_track_active_blocked_and_throughput(tmp_path):
    db_path = tmp_path / "metrics.db"

    record_session(
        db_path,
        session_id="sess-1",
        repository="acme/demo",
        branch="main",
        head_commit="abc123",
        commit_count=1,
        status="created",
    )
    record_session(
        db_path,
        session_id="sess-2",
        repository="acme/demo",
        branch="main",
        head_commit="def456",
        commit_count=2,
        status="finished",
        result="success",
    )
    record_session(
        db_path,
        session_id="sess-3",
        repository="acme/other",
        branch="dev",
        head_commit="ghi789",
        commit_count=1,
        status="blocked",
        result="success",
    )

    metrics = get_session_metrics(db_path)

    assert metrics["total"] == 3
    assert metrics["active"] == 2
    assert metrics["blocked"] == 1
    assert metrics["finished"] == 1
    assert metrics["stale"] == 0
    assert metrics["by_status"]["created"] == 1
    assert metrics["by_status"]["finished"] == 1
    assert metrics["by_status"]["blocked"] == 1
    assert metrics["throughput_last_7_days"] >= 3
    assert metrics["creation_success_rate"] == 1.0
    assert metrics["distinct_repositories"] == 2
    assert metrics["distinct_branches"] == 2
    assert metrics["total_commits"] == 4
    assert metrics["by_repository"]["acme/demo"]["total"] == 2
    assert metrics["by_repository"]["acme/demo"]["finished"] == 1
    assert metrics["by_repository"]["acme/other"]["blocked"] == 1
    assert metrics["by_repository"]["acme/other"]["branches"] == 1
    assert "sess-1" in metrics["active_sessions"]
    assert "sess-3" in metrics["active_sessions"]
    assert "sess-2" not in metrics["active_sessions"]


def test_throughput_counts_sqlite_style_timestamps_from_the_previous_day(tmp_path):
    db_path = tmp_path / "metrics.db"
    record_session(
        db_path,
        session_id="sess-1",
        repository="acme/demo",
        branch="main",
        head_commit="abc123",
        commit_count=1,
        status="running",
    )

    recent = datetime.now(timezone.utc) - timedelta(hours=6)
    conn = get_db_connection(db_path)
    conn.execute(
        "UPDATE sessions SET created_at = ? WHERE session_id = ?",
        (recent.strftime("%Y-%m-%d %H:%M:%S"), "sess-1"),
    )
    conn.commit()
    conn.close()

    metrics = get_session_metrics(db_path)

    assert metrics["throughput_24h"] == 1
    assert metrics["throughput_last_7_days"] == 1


def test_dashboard_html_contains_key_overview_and_repo_breakdown(tmp_path):
    db_path = tmp_path / "metrics.db"

    record_session(
        db_path,
        session_id="sess-1",
        repository="acme/demo",
        branch="main",
        head_commit="abc123",
        commit_count=1,
        status="finished",
        result="success",
    )

    html = render_dashboard(db_path)

    assert "Devin Session Dashboard" in html
    assert "Session Creation" in html
    assert "Blocked (awaiting input)" in html
    assert "Avg Commits/Session" in html
    assert "success_rate" not in html
    assert "Total sessions" in html
    assert "setInterval" in html
    assert "poll-status" in html


def test_poll_devin_session_status_updates_status_and_result(tmp_path, monkeypatch):
    db_path = tmp_path / "metrics.db"
    record_session(
        db_path,
        session_id="sess-10",
        repository="acme/demo",
        branch="main",
        head_commit="ccc",
        commit_count=1,
        status="created",
        result=None,
    )

    class DummyResponse:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    def fake_get(url, headers=None, timeout=None):
        return DummyResponse({"status": "finished"})

    monkeypatch.setenv("DEVIN_API_KEY", "demo-key")
    monkeypatch.setenv("DEVIN_ORG_ID", "demo-org")
    monkeypatch.setattr("analytics.requests.get", fake_get)

    result = poll_devin_session_status(db_path, "sess-10")

    assert result["status"] == "finished"
    metrics = get_session_metrics(db_path)
    assert metrics["by_status"]["finished"] == 1
    assert metrics["finished"] == 1
    assert metrics["avg_duration_seconds"] >= 0
