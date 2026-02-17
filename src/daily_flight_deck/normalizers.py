from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

from .config import FlightDeckConfig
from .models import Signal, parse_timestamp

URGENT_KEYWORDS = (
    "urgent",
    "asap",
    "critical",
    "incident",
    "sev",
    "outage",
    "escalation",
    "blocker",
)
DIRECT_REQUEST_MARKERS = ("can you", "could you", "please", "@rory", "rory,")
LOW_SIGNAL_MARKERS = (
    "promotion",
    "reactivation",
    "bonus",
    "sale",
    "unsubscribe",
    "newsletter",
)


def _text_matches(text: str, markers: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in markers)


def _snippet(text: str, limit: int = 200) -> str:
    trimmed = " ".join(text.split())
    if len(trimmed) <= limit:
        return trimmed
    return f"{trimmed[:limit - 3]}..."


def _extract_slack_channel(result: dict[str, Any]) -> str:
    channel = str(result.get("channel_name") or "").strip()
    if channel:
        return channel
    display_title = str(result.get("display_title") or "").strip()
    if display_title.startswith("#"):
        return display_title[1:]
    return ""


def slack_raw_channel_stats(
    results: list[dict[str, Any]],
    config: FlightDeckConfig,
    *,
    top_n: int = 12,
) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    in_scope = 0
    unknown = 0
    for row in results:
        channel = _extract_slack_channel(row)
        if not channel:
            unknown += 1
            continue
        normalized = config.slack.normalize_channel_name(channel)
        counts[normalized] += 1
        if config.slack.is_in_scope(normalized):
            in_scope += 1
    top_channels = [{"channel": name, "count": count} for name, count in counts.most_common(top_n)]
    return {
        "in_scope_count": in_scope,
        "unknown_channel_count": unknown,
        "top_channels": top_channels,
    }


def normalize_slack(
    results: list[dict[str, Any]],
    config: FlightDeckConfig,
    now: datetime,
) -> list[Signal]:
    output: list[Signal] = []
    for result in results:
        channel = _extract_slack_channel(result)
        if not channel or not config.slack.is_in_scope(channel):
            continue

        raw_text = str(result.get("text") or "")
        timestamp = parse_timestamp(result.get("message_ts"))
        if timestamp < now - timedelta(hours=config.email.lookback_hours):
            continue

        urgency_signals: list[str] = []
        if _text_matches(raw_text, DIRECT_REQUEST_MARKERS):
            urgency_signals.append("direct_request")
        if _text_matches(raw_text, URGENT_KEYWORDS):
            urgency_signals.append("urgent_keyword")
        if "?" in raw_text and _text_matches(raw_text, ("need", "can", "please", "help", "review")):
            urgency_signals.append("unanswered_action_request")

        action = "Review thread and decide if action is needed."
        if "direct_request" in urgency_signals:
            action = "Reply in thread with next step and ETA."
        elif "urgent_keyword" in urgency_signals:
            action = "Acknowledge in channel and triage owner/ETA."

        output.append(
            Signal(
                source="slack",
                item_id=str(result.get("message_info_str") or result.get("web_link") or ""),
                url=str(result.get("display_url") or result.get("web_link") or ""),
                channel_or_sender=channel,
                title=f"#{channel}",
                snippet=_snippet(raw_text),
                timestamp=timestamp,
                urgency_signals=urgency_signals,
                recommended_action=action,
                metadata={"author": result.get("author_display_name") or result.get("author_username") or ""},
            )
        )
    return output


def normalize_calendar(events: list[dict[str, Any]], now: datetime, lookahead_hours: int) -> list[Signal]:
    output: list[Signal] = []
    end_window = now + timedelta(hours=lookahead_hours)
    for event in events:
        start = parse_timestamp(event.get("start"))
        end = parse_timestamp(event.get("end"))
        if start < now or start > end_window:
            continue

        urgency_signals: list[str] = []
        if start <= now + timedelta(hours=2):
            urgency_signals.append("meeting_within_2h")

        title = str(event.get("summary") or "Calendar event")
        description = str(event.get("description") or "")
        action = "Confirm prep materials and attendee expectations."
        if "meeting_within_2h" in urgency_signals:
            action = "Prep talking points/docs and confirm agenda now."

        output.append(
            Signal(
                source="calendar",
                item_id=str(event.get("id") or title),
                url=str(event.get("display_url") or event.get("url") or ""),
                channel_or_sender="calendar",
                title=title,
                snippet=_snippet(description) if description.strip() else "No description",
                timestamp=start,
                urgency_signals=urgency_signals,
                recommended_action=action,
                metadata={"start": start.isoformat(), "end": end.isoformat()},
            )
        )
    return output


def normalize_gmail(emails: list[dict[str, Any]], now: datetime, lookback_hours: int) -> list[Signal]:
    output: list[Signal] = []
    min_time = now - timedelta(hours=lookback_hours)
    for email in emails:
        timestamp = parse_timestamp(email.get("email_ts"))
        if timestamp < min_time:
            continue

        subject = str(email.get("subject") or "(no subject)")
        snippet = str(email.get("snippet") or "")
        sender = str(email.get("from_") or "unknown")
        labels = tuple(str(label) for label in (email.get("labels") or []))
        full_text = f"{subject}\n{snippet}\n{sender}\n{' '.join(labels)}"

        urgency_signals: list[str] = []
        if _text_matches(full_text, DIRECT_REQUEST_MARKERS):
            urgency_signals.append("direct_request")
        if _text_matches(full_text, URGENT_KEYWORDS):
            urgency_signals.append("urgent_keyword")
        if "?" in full_text and _text_matches(full_text, ("need", "can", "please", "review", "action")):
            urgency_signals.append("unanswered_action_request")
        if "CATEGORY_PROMOTIONS" in labels or _text_matches(full_text, LOW_SIGNAL_MARKERS):
            urgency_signals.append("low_signal")

        action = "Review and decide follow-up."
        if "low_signal" in urgency_signals:
            action = "Defer unless this affects today."
        elif "direct_request" in urgency_signals:
            action = "Reply with owner, next step, and ETA."

        output.append(
            Signal(
                source="gmail",
                item_id=str(email.get("id") or ""),
                url=str(email.get("display_url") or ""),
                channel_or_sender=sender,
                title=subject,
                snippet=_snippet(snippet),
                timestamp=timestamp,
                urgency_signals=urgency_signals,
                recommended_action=action,
                metadata={"labels": labels, "has_attachment": bool(email.get("has_attachment"))},
            )
        )
    return output


def normalize_all(
    config: FlightDeckConfig,
    now: datetime | None,
    slack_results: list[dict[str, Any]],
    calendar_events: list[dict[str, Any]],
    gmail_emails: list[dict[str, Any]],
) -> list[Signal]:
    current = now or datetime.now(tz=timezone.utc)
    signals: list[Signal] = []
    signals.extend(normalize_slack(slack_results, config=config, now=current))
    signals.extend(normalize_calendar(calendar_events, now=current, lookahead_hours=config.calendar.lookahead_hours))
    signals.extend(normalize_gmail(gmail_emails, now=current, lookback_hours=config.email.lookback_hours))
    return signals
