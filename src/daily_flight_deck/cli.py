from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .brief import render_brief
from .config import load_config
from .delivery import post_to_slack_webhook
from .normalizers import normalize_all
from .scoring import score_and_sort


def _read_json_file(path: str | None) -> list[dict[str, Any]]:
    if not path:
        return []
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        if "results" in payload and isinstance(payload["results"], list):
            return payload["results"]
        if "events" in payload and isinstance(payload["events"], list):
            return payload["events"]
        if "emails" in payload and isinstance(payload["emails"], list):
            return payload["emails"]
        return []
    if isinstance(payload, list):
        return payload
    return []


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a Daily Flight Deck brief.")
    parser.add_argument("--config", required=True, help="Path to daily_flight_deck.yaml")
    parser.add_argument("--slack-json", help="Path to raw Slack MCP payload")
    parser.add_argument("--calendar-json", help="Path to raw Calendar MCP payload")
    parser.add_argument("--gmail-json", help="Path to raw Gmail MCP payload")
    parser.add_argument("--now", help="Optional ISO timestamp for deterministic runs")
    parser.add_argument("--output-file", help="Write brief to file instead of stdout")
    parser.add_argument("--post", action="store_true", help="Post to Slack webhook")
    return parser.parse_args()


def _parse_now(text: str | None) -> datetime:
    if not text:
        return datetime.now(tz=timezone.utc)
    value = text.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def main() -> int:
    args = _parse_args()
    config = load_config(args.config)
    now = _parse_now(args.now)

    slack_payload = _read_json_file(args.slack_json)
    calendar_payload = _read_json_file(args.calendar_json)
    gmail_payload = _read_json_file(args.gmail_json)

    signals = normalize_all(
        config=config,
        now=now,
        slack_results=slack_payload,
        calendar_events=calendar_payload,
        gmail_emails=gmail_payload,
    )
    ranked = score_and_sort(signals, now=now)
    brief = render_brief(ranked, now=now, max_actions=config.brief.max_actions)

    if args.output_file:
        Path(args.output_file).write_text(brief, encoding="utf-8")
    else:
        print(brief)

    if args.post:
        webhook = os.getenv("SLACK_WEBHOOK_URL", "")
        if not webhook:
            print("SLACK_WEBHOOK_URL is required when --post is set.", file=sys.stderr)
            return 2
        success, status = post_to_slack_webhook(webhook, brief)
        print(status, file=sys.stderr)
        if not success:
            fallback_email = os.getenv("BRIEF_FALLBACK_EMAIL", "roryh@openai.com")
            print(
                f"Webhook failed. Fallback email requested for {fallback_email}.",
                file=sys.stderr,
            )
            return 3

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
