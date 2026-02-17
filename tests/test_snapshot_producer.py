from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from daily_flight_deck.config import load_config
from daily_flight_deck.snapshot_producer import SnapshotProducer, _parse_payload
from daily_flight_deck.storage import Storage


ROOT = Path(__file__).resolve().parents[1]


def test_snapshot_producer_stores_snapshot_and_tasks(tmp_path) -> None:
    base_config = load_config(ROOT / "config" / "daily_flight_deck.yaml")
    test_config = replace(
        base_config,
        dashboard=replace(
            base_config.dashboard,
            db_path=str(tmp_path / "flight_deck.db"),
            snapshot_path=str(tmp_path / "latest_snapshot.json"),
        ),
    )

    storage = Storage(tmp_path / "flight_deck.db")
    storage.init_db()
    producer = SnapshotProducer(config=test_config, storage=storage, project_root=ROOT)

    payload_json = json.loads((ROOT / "tests" / "fixtures" / "full_snapshot_payload.json").read_text(encoding="utf-8"))
    now = datetime.now(tz=timezone.utc)
    for idx, row in enumerate(payload_json["slack_results"]):
        row["message_ts"] = (now - timedelta(minutes=30 + idx * 5)).isoformat()
    for idx, row in enumerate(payload_json["gmail_emails"]):
        row["email_ts"] = (now - timedelta(minutes=45 + idx * 7)).isoformat()
    for idx, row in enumerate(payload_json["calendar_events"]):
        start = now + timedelta(minutes=40 + idx * 60)
        end = start + timedelta(minutes=30)
        row["start"] = start.isoformat()
        row["end"] = end.isoformat()
    payload = _parse_payload(payload_json)
    result = producer.produce(source="manual", payload=payload)

    assert result["signal_count"] > 0
    assert result["task_count"] > 0
    assert (tmp_path / "latest_snapshot.json").exists()

    latest = storage.get_latest_snapshot()
    assert latest is not None
    assert latest.metadata["in_scope_raw_counts"]["slack"] >= 1
    assert latest.metadata["slack_channel_stats"]["top_channels"]
    tasks = storage.list_board_tasks(latest.id)
    assert tasks


def test_fetch_from_codex_enables_connectors_flag(monkeypatch, tmp_path) -> None:
    base_config = load_config(ROOT / "config" / "daily_flight_deck.yaml")
    test_config = replace(
        base_config,
        dashboard=replace(
            base_config.dashboard,
            db_path=str(tmp_path / "flight_deck.db"),
            snapshot_path=str(tmp_path / "latest_snapshot.json"),
        ),
    )
    storage = Storage(tmp_path / "flight_deck.db")
    storage.init_db()
    producer = SnapshotProducer(config=test_config, storage=storage, project_root=ROOT)
    producer.preflight_checks = lambda: None  # type: ignore[assignment]

    captured_command: dict[str, list[str]] = {}

    def fake_run(command, capture_output, text, check, timeout):
        captured_command["argv"] = list(command)
        out_index = command.index("--output-last-message") + 1
        out_path = Path(command[out_index])
        out_path.write_text(
            json.dumps(
                {
                    "slack_results": [],
                    "calendar_events": [],
                    "gmail_emails": [
                        {
                            "id": "msg_1",
                            "subject": "Follow up needed",
                            "snippet": "Can you send update?",
                            "email_ts": datetime.now(tz=timezone.utc).isoformat(),
                            "from_": "owner@example.com",
                            "labels": ["INBOX"],
                            "display_url": "https://mail.google.com/mail/#all/msg_1",
                        }
                    ],
                    "diagnostics": {
                        "tool_access": {"slack": "ok", "calendar": "ok", "gmail": "ok"},
                        "errors": [],
                    },
                }
            ),
            encoding="utf-8",
        )
        return SimpleNamespace(returncode=0, stderr="", stdout="")

    monkeypatch.setattr("daily_flight_deck.snapshot_producer.subprocess.run", fake_run)
    payload = producer.fetch_from_codex()
    argv = captured_command["argv"]
    assert "--enable" in argv
    assert "connectors" in argv
    assert payload.gmail_emails
