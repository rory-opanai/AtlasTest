from __future__ import annotations

from datetime import datetime, timedelta

from .models import Signal


def _fmt_signal(signal: Signal) -> str:
    link = f" ([Open]({signal.url}))" if signal.url else ""
    reasons = f" | {'; '.join(signal.score_reasons)}" if signal.score_reasons else ""
    return (
        f"- [{signal.source}] **{signal.title}** from `{signal.channel_or_sender}` "
        f"(score: {signal.score}){reasons}\n"
        f"  - Snippet: {signal.snippet}\n"
        f"  - Action: {signal.recommended_action}{link}"
    )


def _find_calendar_collisions(calendar_items: list[Signal]) -> list[str]:
    collisions: list[str] = []
    sorted_items = sorted(calendar_items, key=lambda item: item.timestamp)
    for i in range(len(sorted_items) - 1):
        current = sorted_items[i]
        nxt = sorted_items[i + 1]
        current_end = datetime.fromisoformat(current.metadata.get("end", current.timestamp.isoformat()))
        if nxt.timestamp < current_end:
            collisions.append(
                f"- **Collision:** `{current.title}` overlaps with `{nxt.title}`"
            )
    return collisions


def render_brief(
    signals: list[Signal],
    now: datetime,
    max_actions: int,
) -> str:
    top_ranked = signals[:max_actions]
    top_actions = top_ranked[:5]
    time_critical = [
        item for item in top_ranked if "meeting_within_2h" in item.urgency_signals or item.score >= 50
    ]
    calendar_items = [item for item in signals if item.source == "calendar"]
    calendar_collisions = _find_calendar_collisions(calendar_items)
    inbox_watchlist = [item for item in signals if item.source == "gmail"][:5]
    deferred = [item for item in reversed(signals) if item.score <= 0][:5]
    start_here = top_actions[0] if top_actions else None

    lines: list[str] = []
    lines.append(f"# SE Daily Flight Deck ({now.date().isoformat()})")
    lines.append("")
    lines.append("## Top 5 Actions for Today")
    if top_actions:
        lines.extend(_fmt_signal(item) for item in top_actions)
    else:
        lines.append("- No urgent actions identified.")

    lines.append("")
    lines.append("## Time-Critical in Next 2 Hours")
    if time_critical:
        lines.extend(_fmt_signal(item) for item in time_critical)
    else:
        lines.append("- No time-critical items in the next 2 hours.")

    lines.append("")
    lines.append("## Calendar Collisions / Prep Needed")
    if calendar_collisions:
        lines.extend(calendar_collisions)
    else:
        lines.append("- No calendar collisions detected.")
    for event in calendar_items[:3]:
        if event.timestamp <= now + timedelta(hours=4):
            lines.append(f"- Prep: `{event.title}` at {event.timestamp.isoformat()} -> {event.recommended_action}")

    lines.append("")
    lines.append("## Inbox Watchlist (Last 24h)")
    if inbox_watchlist:
        lines.extend(_fmt_signal(item) for item in inbox_watchlist)
    else:
        lines.append("- No inbox items in the configured lookback window.")

    lines.append("")
    lines.append("## Deferred / Low Priority")
    if deferred:
        lines.extend(_fmt_signal(item) for item in deferred)
    else:
        lines.append("- No deferred items.")

    lines.append("")
    lines.append("## One Recommended First Task (start here)")
    if start_here:
        lines.append(_fmt_signal(start_here))
    else:
        lines.append("- Start by checking Slack mentions and immediate calendar prep.")

    return "\n".join(lines)
