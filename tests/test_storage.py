from __future__ import annotations

from datetime import datetime, timezone

from daily_flight_deck.models import Signal
from daily_flight_deck.storage import Storage


def test_storage_snapshot_and_task_lifecycle(tmp_path) -> None:
    db_path = tmp_path / "flight_deck.db"
    storage = Storage(db_path)
    storage.init_db()

    signals = [
        Signal(
            source="slack",
            item_id="1",
            url="https://example.com/1",
            channel_or_sender="codex-app-feedback",
            title="#codex-app-feedback",
            snippet="Need urgent response",
            timestamp=datetime(2026, 2, 16, 7, 0, tzinfo=timezone.utc),
            urgency_signals=["direct_request"],
            recommended_action="Reply quickly",
            score=35,
            score_reasons=["+35 direct request"],
            metadata={},
        )
    ]
    snapshot_id = storage.insert_snapshot(signals, {"slack": 1, "calendar": 0, "gmail": 0})
    storage.replace_auto_tasks_for_snapshot(
        snapshot_id,
        [
            {
                "source": "slack",
                "priority_bucket": "next",
                "title": "Respond to #codex-app-feedback",
                "action_hint": "Reply quickly",
                "status": "todo",
                "due_at": None,
                "url": "https://example.com/1",
                "metadata": {},
            }
        ],
    )
    manual_id = storage.create_manual_task("Prepare customer notes", "Draft summary", priority_bucket="now")
    storage.update_task_status(manual_id, "in_progress")
    storage.record_refresh_event(kind="manual", status="success", message="ok")

    latest = storage.get_latest_snapshot()
    assert latest is not None
    assert latest.id == snapshot_id

    tasks = storage.list_board_tasks(snapshot_id)
    assert len(tasks) == 2
    assert any(task.manual for task in tasks)
    assert any(task.status == "in_progress" for task in tasks)

    allowed, _ = storage.can_refresh_now(10)
    assert not allowed


def test_can_refresh_now_allows_immediate_retry_after_failed_refresh(tmp_path) -> None:
    db_path = tmp_path / "flight_deck.db"
    storage = Storage(db_path)
    storage.init_db()

    storage.record_refresh_event(kind="manual", status="failed", message="connector unavailable")
    allowed, next_allowed = storage.can_refresh_now(10)
    assert allowed
    assert next_allowed is None
