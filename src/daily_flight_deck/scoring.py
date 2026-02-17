from __future__ import annotations

from datetime import datetime

from .models import Signal


def score_signal(signal: Signal) -> Signal:
    score = 0
    reasons: list[str] = []

    if "meeting_within_2h" in signal.urgency_signals:
        score += 50
        reasons.append("+50 meeting within 2h")
    if "direct_request" in signal.urgency_signals:
        score += 35
        reasons.append("+35 direct request")
    if "urgent_keyword" in signal.urgency_signals:
        score += 25
        reasons.append("+25 escalation/urgent keyword")
    if "unanswered_action_request" in signal.urgency_signals:
        score += 20
        reasons.append("+20 unanswered action request")
    if "low_signal" in signal.urgency_signals:
        score -= 20
        reasons.append("-20 low signal/promotion")

    signal.score = score
    signal.score_reasons = reasons
    return signal


def score_and_sort(signals: list[Signal], now: datetime | None = None) -> list[Signal]:
    _ = now
    scored = [score_signal(signal) for signal in signals]
    return sorted(scored, key=lambda s: (-s.score, s.timestamp))
