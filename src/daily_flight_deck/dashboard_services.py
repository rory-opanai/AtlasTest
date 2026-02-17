from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from .models import Signal
from .storage import TaskRecord

ACTION_TYPE_LABELS = {
    "draft_slack_reply": "Draft Slack Reply",
    "draft_email_reply": "Draft Email Reply",
    "meeting_prep_brief": "Generate Meeting Prep Brief",
    "prioritized_execution_plan": "Generate Prioritized Execution Plan",
}


def derive_tasks_from_signals(signals: list[Signal], now: datetime | None = None) -> list[dict[str, Any]]:
    current = now or datetime.now(tz=timezone.utc)
    tasks: list[dict[str, Any]] = []
    for signal in signals:
        bucket = "later"
        if signal.score >= 50 or "meeting_within_2h" in signal.urgency_signals:
            bucket = "now"
        elif signal.score >= 20:
            bucket = "next"

        due_at = None
        if signal.source == "calendar":
            due_at = signal.timestamp.isoformat()
        elif signal.timestamp >= current and signal.timestamp <= current + timedelta(hours=8):
            due_at = signal.timestamp.isoformat()

        tasks.append(
            {
                "source": signal.source,
                "priority_bucket": bucket,
                "title": signal.title,
                "action_hint": signal.recommended_action,
                "status": "todo",
                "due_at": due_at,
                "url": signal.url,
                "metadata": {
                    "score": signal.score,
                    "score_reasons": signal.score_reasons,
                    "channel_or_sender": signal.channel_or_sender,
                    "snippet": signal.snippet,
                },
            }
        )
    return tasks


def group_tasks(tasks: list[TaskRecord]) -> dict[str, list[TaskRecord]]:
    grouped: dict[str, list[TaskRecord]] = {"now": [], "next": [], "later": []}
    for task in tasks:
        grouped.setdefault(task.priority_bucket, []).append(task)
    for bucket in grouped:
        grouped[bucket] = sorted(
            grouped[bucket],
            key=lambda item: (
                0 if item.status == "in_progress" else 1,
                item.due_at.isoformat() if item.due_at else "9999-12-31",
                item.id,
            ),
        )
    return grouped


def build_source_panels(signals: list[Signal]) -> dict[str, list[Signal]]:
    by_source: dict[str, list[Signal]] = defaultdict(list)
    for signal in signals:
        by_source[signal.source].append(signal)

    calendar_items = sorted(by_source.get("calendar", []), key=lambda item: item.timestamp)[:8]
    gmail_items = sorted(by_source.get("gmail", []), key=lambda item: -item.score)[:8]
    slack_items = sorted(by_source.get("slack", []), key=lambda item: -item.score)[:8]
    return {
        "calendar": calendar_items,
        "gmail": gmail_items,
        "slack": slack_items,
    }


def source_counts(signals: list[Signal]) -> dict[str, int]:
    counts: dict[str, int] = {"slack": 0, "calendar": 0, "gmail": 0}
    for signal in signals:
        counts[signal.source] = counts.get(signal.source, 0) + 1
    return counts
