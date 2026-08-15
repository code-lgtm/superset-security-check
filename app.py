import hashlib
import hmac
from typing import Any, Dict, List


def verify_signature(payload: bytes, signature: str, secret: str) -> bool:
    """Validate an HMAC signature for an incoming webhook payload."""
    if not signature or not secret:
        return False

    expected = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def extract_commits(event: Dict[str, Any]) -> Dict[str, Any]:
    """Return a normalized summary of repository and commit info from a push payload."""
    ref = event.get("ref", "")
    branch = ref.replace("refs/heads/", "") if ref.startswith("refs/heads/") else ref
    repository = event.get("repository", {}).get("full_name", "unknown")
    commits: List[Dict[str, Any]] = event.get("commits", []) or []

    return {
        "repository": repository,
        "branch": branch,
        "head_commit": event.get("head_commit", {}).get("id", ""),
        "commit_count": len(commits),
        "messages": [item.get("message", "") for item in commits],
    }
