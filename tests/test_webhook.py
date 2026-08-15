import hashlib
import hmac

from app import extract_commits, verify_signature


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
