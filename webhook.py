import os
from typing import Any, Dict

import requests
from flask import Flask, abort, jsonify, request

from app import extract_commits, verify_signature

app = Flask(__name__)


def build_devin_session_payload(summary: Dict[str, Any]) -> Dict[str, Any]:
    repository = summary.get("repository", "unknown")
    branch = summary.get("branch", "unknown")
    messages = summary.get("messages", []) or []
    playbook_id = os.environ.get("DEVIN_PLAYBOOK_ID", "")

    prompt_parts = [
        f"Repository: {repository}",
        f"Branch: {branch}",
        "Recent commit messages:",
    ]
    if messages:
        prompt_parts.extend(f"- {message}" for message in messages)
    else:
        prompt_parts.append("No commit messages provided.")
    
    prompt = (
        "Run a security review of https://github.com/code-lgtm/superset "
        "(branch: master). Deliverable: "
        "security-review.md report only, no fix PRs."
    )

    payload = {
        "name": f"Webhook commit - {repository}:{branch}",
        "prompt": "\n".join(prompt_parts),
    }
    if playbook_id:
        payload["playbook_id"] = playbook_id

    return payload


def create_devin_session(summary: Dict[str, Any]) -> Dict[str, Any]:
    api_key = os.environ.get("DEVIN_API_KEY", "")
    org_id = os.environ.get("DEVIN_ORG_ID", "")
    base_url = os.environ.get("DEVIN_API_BASE_URL", "https://api.devin.ai/v3")

    if not api_key or not org_id:
        raise RuntimeError("DEVIN_API_KEY and DEVIN_ORG_ID must be configured")

    url = f"{base_url}/organizations/{org_id}/sessions"
    payload = build_devin_session_payload(summary)
    response = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


@app.route("/health", methods=["GET"])
def health() -> Any:
    return jsonify({"status": "ok"})


@app.route("/webhook/commit", methods=["POST"])
def commit_webhook() -> Any:
    webhook_secret = os.environ.get("WEBHOOK_SECRET", "change-me")
    payload = request.get_data()
    signature = request.headers.get("X-Hub-Signature-256", "")

    if signature.startswith("sha256="):
        signature = signature.split("=", 1)[1]

    if not verify_signature(payload, signature, webhook_secret):
        abort(401)

    event = request.get_json(silent=True) or {}
    summary = extract_commits(event)

    print(f"Received webhook for {summary['repository']} on branch {summary['branch']}")

    try:
        devin_result = create_devin_session(summary)
    except Exception as exc:  # pragma: no cover - webhook-level safety
        devin_result = {"error": str(exc)}

    return jsonify({
        "status": "received",
        "repository": summary["repository"],
        "branch": summary["branch"],
        "head_commit": summary["head_commit"],
        "commit_count": summary["commit_count"],
        "messages": summary["messages"],
        "devin": devin_result,
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
