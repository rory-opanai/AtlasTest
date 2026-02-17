from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from daily_flight_deck.brief import render_brief
from daily_flight_deck.config import load_config
from daily_flight_deck.normalizers import normalize_all
from daily_flight_deck.scoring import score_and_sort


ROOT = Path(__file__).resolve().parents[1]


def _load_fixture(name: str) -> list[dict]:
    payload = json.loads((ROOT / "tests" / "fixtures" / name).read_text(encoding="utf-8"))
    if "results" in payload:
        return payload["results"]
    if "events" in payload:
        return payload["events"]
    if "emails" in payload:
        return payload["emails"]
    return []


def test_channel_scope_supports_exact_and_prefix() -> None:
    config = load_config(ROOT / "config" / "daily_flight_deck.yaml")
    assert config.slack.is_in_scope("codex-app-feedback")
    assert config.slack.is_in_scope("tmp-gpt5-api-deployment-ops")
    assert not config.slack.is_in_scope("random-channel")


def test_weighted_scoring_applies_required_rules() -> None:
    config = load_config(ROOT / "config" / "daily_flight_deck.yaml")
    now = datetime(2026, 2, 16, 7, 0, tzinfo=timezone.utc)

    signals = normalize_all(
        config=config,
        now=now,
        slack_results=_load_fixture("slack.json"),
        calendar_events=_load_fixture("calendar.json"),
        gmail_emails=_load_fixture("gmail.json"),
    )
    ranked = score_and_sort(signals, now=now)
    assert ranked
    top = ranked[0]
    assert top.score >= 60
    assert any(reason.startswith("+50") or reason.startswith("+35") for reason in top.score_reasons)

    low = [item for item in ranked if "low_signal" in item.urgency_signals]
    assert low
    assert low[0].score <= 0


def test_brief_has_all_required_sections() -> None:
    config = load_config(ROOT / "config" / "daily_flight_deck.yaml")
    now = datetime(2026, 2, 16, 7, 0, tzinfo=timezone.utc)
    ranked = score_and_sort(
        normalize_all(
            config=config,
            now=now,
            slack_results=_load_fixture("slack.json"),
            calendar_events=_load_fixture("calendar.json"),
            gmail_emails=_load_fixture("gmail.json"),
        ),
        now=now,
    )
    brief = render_brief(ranked, now=now, max_actions=config.brief.max_actions)
    required_headers = [
        "## Top 5 Actions for Today",
        "## Time-Critical in Next 2 Hours",
        "## Calendar Collisions / Prep Needed",
        "## Inbox Watchlist (Last 24h)",
        "## Deferred / Low Priority",
        "## One Recommended First Task (start here)",
    ]
    for header in required_headers:
        assert header in brief
