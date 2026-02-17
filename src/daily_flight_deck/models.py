from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class Signal:
    source: str
    item_id: str
    url: str
    channel_or_sender: str
    title: str
    snippet: str
    timestamp: datetime
    urgency_signals: list[str] = field(default_factory=list)
    recommended_action: str = ""
    score: int = 0
    score_reasons: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


def signal_to_dict(signal: Signal) -> dict[str, Any]:
    return {
        "source": signal.source,
        "item_id": signal.item_id,
        "url": signal.url,
        "channel_or_sender": signal.channel_or_sender,
        "title": signal.title,
        "snippet": signal.snippet,
        "timestamp": signal.timestamp.isoformat(),
        "urgency_signals": list(signal.urgency_signals),
        "recommended_action": signal.recommended_action,
        "score": signal.score,
        "score_reasons": list(signal.score_reasons),
        "metadata": dict(signal.metadata),
    }


def signal_from_dict(payload: dict[str, Any]) -> Signal:
    return Signal(
        source=str(payload.get("source", "")),
        item_id=str(payload.get("item_id", "")),
        url=str(payload.get("url", "")),
        channel_or_sender=str(payload.get("channel_or_sender", "")),
        title=str(payload.get("title", "")),
        snippet=str(payload.get("snippet", "")),
        timestamp=parse_timestamp(payload.get("timestamp")),
        urgency_signals=[str(x) for x in payload.get("urgency_signals", [])],
        recommended_action=str(payload.get("recommended_action", "")),
        score=int(payload.get("score", 0)),
        score_reasons=[str(x) for x in payload.get("score_reasons", [])],
        metadata=dict(payload.get("metadata", {})),
    )


def parse_timestamp(value: str | int | float | None) -> datetime:
    if value is None:
        return datetime.now(tz=timezone.utc)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    text = str(value).strip()
    if text.endswith("Z"):
        text = text.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        try:
            return datetime.fromtimestamp(float(text), tz=timezone.utc)
        except ValueError:
            return datetime.now(tz=timezone.utc)
