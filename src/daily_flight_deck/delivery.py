from __future__ import annotations

import json
from urllib import error, request


def post_to_slack_webhook(webhook_url: str, message: str, timeout_seconds: int = 10) -> tuple[bool, str]:
    payload = json.dumps({"text": message}).encode("utf-8")
    req = request.Request(
        webhook_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=timeout_seconds) as response:
            status = getattr(response, "status", 200)
            if 200 <= status < 300:
                return True, f"Slack webhook accepted ({status})."
            return False, f"Slack webhook returned status {status}."
    except error.URLError as exc:
        return False, f"Slack webhook failed: {exc}"
