from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .config import FlightDeckConfig, load_config
from .dashboard_services import derive_tasks_from_signals, source_counts
from .models import signal_to_dict
from .normalizers import normalize_all
from .scoring import score_and_sort
from .storage import Storage


@dataclass(frozen=True)
class SnapshotPayload:
    slack_results: list[dict[str, Any]]
    calendar_events: list[dict[str, Any]]
    gmail_emails: list[dict[str, Any]]
    fetch_mode: str
    diagnostics: dict[str, Any]


class SnapshotProducer:
    def __init__(self, *, config: FlightDeckConfig, storage: Storage, project_root: Path):
        self.config = config
        self.storage = storage
        self.project_root = project_root
        self.snapshot_output_path = project_root / config.dashboard.snapshot_path
        self.prompt_path = project_root / "prompts" / "snapshot_fetch_prompt.md"

    def safe_produce(self, *, source: str = "scheduled", payload: SnapshotPayload | None = None) -> dict[str, Any]:
        try:
            result = self.produce(source=source, payload=payload)
            self.storage.record_refresh_event(kind=source, status="success", message=f"snapshot:{result['snapshot_id']}")
            return result
        except Exception as exc:
            message = str(exc).strip()
            if len(message) > 400:
                message = f"{message[:397]}..."
            self.storage.record_refresh_event(kind=source, status="failed", message=message)
            raise

    def preflight_checks(self) -> None:
        self._assert_cli_connector_config()

    def produce(self, *, source: str = "scheduled", payload: SnapshotPayload | None = None) -> dict[str, Any]:
        current = datetime.now(tz=timezone.utc)
        if payload is None:
            payload = self.fetch_from_codex()

        raw_counts = {
            "slack": len(payload.slack_results),
            "calendar": len(payload.calendar_events),
            "gmail": len(payload.gmail_emails),
        }
        signals = normalize_all(
            config=self.config,
            now=current,
            slack_results=payload.slack_results,
            calendar_events=payload.calendar_events,
            gmail_emails=payload.gmail_emails,
        )
        ranked = score_and_sort(signals, now=current)
        counts = source_counts(ranked)
        snapshot_id = self.storage.insert_snapshot(
            ranked,
            counts,
            created_at=current,
            source=source,
            status="ready",
            metadata={
                "fetch_mode": payload.fetch_mode,
                "raw_counts": raw_counts,
                "actionable_counts": counts,
                "diagnostics": payload.diagnostics,
                "schedule": {"run_days": list(self.config.run_days), "run_time": self.config.run_time},
            },
        )
        tasks = derive_tasks_from_signals(ranked, now=current)
        self.storage.replace_auto_tasks_for_snapshot(snapshot_id, tasks)
        self.storage.cleanup_old(self.config.dashboard.retention_days)
        self._write_snapshot_file(snapshot_id=snapshot_id, created_at=current, counts=counts, signals=ranked)
        return {
            "snapshot_id": snapshot_id,
            "created_at": current.isoformat(),
            "source_counts": counts,
            "signal_count": len(ranked),
            "task_count": len(tasks),
            "raw_counts": raw_counts,
            "fetch_mode": payload.fetch_mode,
        }

    def fetch_from_codex(self) -> SnapshotPayload:
        self.preflight_checks()
        now = datetime.now(tz=timezone.utc)
        slack_after_date = (now - timedelta(hours=self.config.email.lookback_hours)).date().isoformat()
        calendar_time_min = now.isoformat()
        calendar_time_max = (now + timedelta(hours=self.config.calendar.lookahead_hours)).isoformat()

        prompt_body = self.prompt_path.read_text(encoding="utf-8")
        prompt = (
            f"{prompt_body}\n\n"
            f"run_days={','.join(self.config.run_days)} run_time={self.config.run_time}\n"
            f"email_lookback_hours={self.config.email.lookback_hours}\n"
            f"calendar_lookahead_hours={self.config.calendar.lookahead_hours}\n"
            f"slack_after_date={slack_after_date}\n"
            f"calendar_time_min={calendar_time_min}\n"
            f"calendar_time_max={calendar_time_max}\n"
        )
        with tempfile.NamedTemporaryFile(mode="w+", suffix=".json", delete=True) as out_file:
            command = [
                self.config.runtime.codex_bin,
                "exec",
                "--enable",
                "connectors",
                "--skip-git-repo-check",
                "-C",
                str(self.project_root),
                "-m",
                self.config.runtime.codex_exec_model,
                "--output-last-message",
                out_file.name,
                prompt,
            ]
            proc = subprocess.run(command, capture_output=True, text=True, check=False, timeout=900)
            out_file.seek(0)
            raw = out_file.read().strip()
        if proc.returncode != 0:
            error = proc.stderr.strip() or proc.stdout.strip() or "Unknown codex exec failure"
            raise RuntimeError(f"Snapshot fetch failed: {error}")
        if not raw:
            context = proc.stderr.strip() or proc.stdout.strip() or "codex exec returned empty output"
            raise RuntimeError(f"Snapshot payload missing from codex exec: {context}")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Snapshot payload JSON parse failed: {exc}") from exc
        parsed = _parse_payload(payload, fetch_mode="codex_exec")
        self._assert_not_synthetic(parsed)
        self._assert_not_empty(parsed)
        return parsed

    def _assert_cli_connector_config(self) -> None:
        config_path = Path.home() / ".codex" / "config.toml"
        if not config_path.exists():
            raise RuntimeError(
                "Codex CLI config missing at ~/.codex/config.toml; cannot verify Slack/Gmail/Calendar connectors."
            )
        text = config_path.read_text(encoding="utf-8")
        sections = set(re.findall(r"^\[mcp_servers\.([^\]]+)\]", text, flags=re.MULTILINE))
        required_candidates = {"codex_apps", "slack", "gmail", "google_calendar"}
        if sections.isdisjoint(required_candidates):
            seen = ", ".join(sorted(sections)) if sections else "(none)"
            raise RuntimeError(
                "Codex CLI MCP config does not include Slack/Gmail/Calendar connectors. "
                f"Found servers: {seen}. Add codex_apps or dedicated connector MCP entries."
            )

    def _assert_not_synthetic(self, payload: SnapshotPayload) -> None:
        urls: list[str] = []
        for row in payload.slack_results:
            urls.append(str(row.get("display_url") or row.get("web_link") or ""))
        for row in payload.gmail_emails:
            urls.append(str(row.get("display_url") or ""))
        for row in payload.calendar_events:
            urls.append(str(row.get("display_url") or row.get("url") or ""))
        lowered = "\n".join(urls).lower()
        if ".example/" in lowered or ".example.com" in lowered or "slack.example" in lowered or "mail.example" in lowered:
            raise RuntimeError(
                "Snapshot fetch returned synthetic/example-domain content. "
                "Refusing to ingest non-live data."
            )

    def _assert_not_empty(self, payload: SnapshotPayload) -> None:
        total = len(payload.slack_results) + len(payload.calendar_events) + len(payload.gmail_emails)
        allow_empty = os.getenv("FLIGHT_DECK_ALLOW_EMPTY_SNAPSHOT", "").strip().lower() in {"1", "true", "yes"}
        if total == 0 and not allow_empty:
            diagnostics = payload.diagnostics or {}
            tool_access = diagnostics.get("tool_access") if isinstance(diagnostics, dict) else None
            errors = diagnostics.get("errors") if isinstance(diagnostics, dict) else None
            details: list[str] = []
            if isinstance(tool_access, dict):
                unavailable = [name for name, status in tool_access.items() if str(status).lower() != "ok"]
                if unavailable:
                    details.append(f"tool_access={','.join(unavailable)}")
            if isinstance(errors, list) and errors:
                details.append(f"errors={'; '.join(str(item) for item in errors[:2])}")
            suffix = f" Diagnostics: {' | '.join(details)}." if details else ""
            raise RuntimeError(
                "No items were returned from Slack/Gmail/Calendar. "
                "This usually means MCP connector access/auth is not active for codex exec. "
                f"Set FLIGHT_DECK_ALLOW_EMPTY_SNAPSHOT=1 only if an empty day is expected.{suffix}"
            )

    def _write_snapshot_file(
        self,
        *,
        snapshot_id: int,
        created_at: datetime,
        counts: dict[str, int],
        signals: list[Any],
    ) -> None:
        self.snapshot_output_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "snapshot_id": snapshot_id,
            "created_at": created_at.isoformat(),
            "source_counts": counts,
            "signals": [signal_to_dict(item) for item in signals],
        }
        self.snapshot_output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _parse_payload(payload: dict[str, Any], fetch_mode: str = "input_json") -> SnapshotPayload:
    slack_results = payload.get("slack_results", payload.get("slack", []))
    calendar_events = payload.get("calendar_events", payload.get("calendar", []))
    gmail_emails = payload.get("gmail_emails", payload.get("gmail", []))
    diagnostics = payload.get("diagnostics")
    if not isinstance(slack_results, list):
        raise ValueError("slack_results must be a list")
    if not isinstance(calendar_events, list):
        raise ValueError("calendar_events must be a list")
    if not isinstance(gmail_emails, list):
        raise ValueError("gmail_emails must be a list")
    if diagnostics is None:
        diagnostics = {}
    if not isinstance(diagnostics, dict):
        raise ValueError("diagnostics must be an object when provided")
    return SnapshotPayload(
        slack_results=[dict(item) for item in slack_results if isinstance(item, dict)],
        calendar_events=[dict(item) for item in calendar_events if isinstance(item, dict)],
        gmail_emails=[dict(item) for item in gmail_emails if isinstance(item, dict)],
        fetch_mode=fetch_mode,
        diagnostics=dict(diagnostics),
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Produce Daily Flight Deck snapshot")
    parser.add_argument("--config", default="config/daily_flight_deck.yaml")
    parser.add_argument("--source", default="scheduled", choices=["scheduled", "manual"])
    parser.add_argument("--input-json", help="Optional payload JSON file to bypass codex fetch")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    project_root = Path.cwd()
    config = load_config(args.config)
    db_path = project_root / config.dashboard.db_path
    storage = Storage(db_path)
    storage.init_db()
    producer = SnapshotProducer(config=config, storage=storage, project_root=project_root)

    payload = None
    if args.input_json:
        parsed = json.loads(Path(args.input_json).read_text(encoding="utf-8"))
        payload = _parse_payload(parsed, fetch_mode="input_json")
    result = producer.safe_produce(source=args.source, payload=payload)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
