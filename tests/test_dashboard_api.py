from __future__ import annotations
from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from daily_flight_deck.dashboard_app import create_app


ROOT = Path(__file__).resolve().parents[1]


def _write_test_config(tmp_path: Path) -> Path:
    base = yaml.safe_load((ROOT / "config" / "daily_flight_deck.yaml").read_text(encoding="utf-8"))
    base["dashboard"]["db_path"] = str(tmp_path / "flight_deck.db")
    base["dashboard"]["snapshot_path"] = str(tmp_path / "latest_snapshot.json")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(base), encoding="utf-8")
    return config_path


def test_dashboard_endpoints_and_refresh_cooldown(tmp_path) -> None:
    config_path = _write_test_config(tmp_path)
    app = create_app(config_path=str(config_path), start_workers=False)
    ctx = app.state.dashboard_context

    def fake_safe_produce(*, source: str = "manual", payload=None):
        ctx.storage.record_refresh_event(kind=source, status="success", message="mock")
        return {"snapshot_id": 0}

    ctx.snapshot_producer.safe_produce = fake_safe_produce  # type: ignore[assignment]
    ctx.snapshot_producer.preflight_checks = lambda: None  # type: ignore[assignment]

    client = TestClient(app)

    home = client.get("/")
    assert home.status_code == 200
    assert "SE Daily Command Center" in home.text

    created = client.post("/api/tasks/manual", json={"title": "Follow up customer", "action_hint": "Send draft"})
    assert created.status_code == 200
    task_id = created.json()["task_id"]

    updated = client.post(f"/api/tasks/{task_id}/status", json={"status": "done"})
    assert updated.status_code == 200
    assert updated.json()["status"] == "done"

    run = client.post(
        "/api/actions/run",
        json={"action_type": "prioritized_execution_plan", "task_id": None, "context": "Focus on top items"},
    )
    assert run.status_code == 200
    run_id = run.json()["run_id"]

    run_state = client.get(f"/api/actions/{run_id}")
    assert run_state.status_code == 200
    assert run_state.json()["status"] == "queued"

    first_refresh = client.post("/api/refresh")
    assert first_refresh.status_code == 200
    second_refresh = client.post("/api/refresh")
    assert second_refresh.status_code == 429


def test_ui_refresh_does_not_fail_when_background_refresh_errors(tmp_path) -> None:
    config_path = _write_test_config(tmp_path)
    app = create_app(config_path=str(config_path), start_workers=False)
    ctx = app.state.dashboard_context

    def fail_safe_produce(*, source: str = "manual", payload=None):
        raise RuntimeError("connector unavailable")

    ctx.snapshot_producer.safe_produce = fail_safe_produce  # type: ignore[assignment]

    client = TestClient(app)
    response = client.post("/ui/refresh")
    assert response.status_code == 200


def test_env_overrides_db_and_snapshot_paths(tmp_path, monkeypatch) -> None:
    config_path = _write_test_config(tmp_path)
    db_override = tmp_path / "override.db"
    snapshot_override = tmp_path / "override_snapshot.json"
    monkeypatch.setenv("FLIGHT_DECK_DB_PATH", str(db_override))
    monkeypatch.setenv("FLIGHT_DECK_SNAPSHOT_PATH", str(snapshot_override))

    app = create_app(config_path=str(config_path), start_workers=False)
    ctx = app.state.dashboard_context

    assert ctx.storage.db_path == db_override
    assert ctx.snapshot_producer.snapshot_output_path == snapshot_override
