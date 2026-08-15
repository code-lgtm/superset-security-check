import os
from typing import Any

from flask import Flask, abort, jsonify, request

from app import extract_commits, verify_signature

app = Flask(__name__)

WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "change-me")


@app.route("/health", methods=["GET"])
def health() -> Any:
    return jsonify({"status": "ok"})


@app.route("/webhook/commit", methods=["POST"])
def commit_webhook() -> Any:
    payload = request.get_data()
    signature = request.headers.get("X-Hub-Signature-256", "")

    if signature.startswith("sha256="):
        signature = signature.split("=", 1)[1]

    if not verify_signature(payload, signature, WEBHOOK_SECRET):
        abort(401)

    event = request.get_json(silent=True) or {}
    summary = extract_commits(event)

    return jsonify({
        "status": "received",
        "repository": summary["repository"],
        "branch": summary["branch"],
        "head_commit": summary["head_commit"],
        "commit_count": summary["commit_count"],
        "messages": summary["messages"],
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
