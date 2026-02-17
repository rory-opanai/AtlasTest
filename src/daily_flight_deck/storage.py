from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .models import Signal, parse_timestamp, signal_from_dict, signal_to_dict

TASK_STATUSES = {"todo", "in_progress", "done", "snoozed"}
PRIORITY_BUCKETS = {"now", "next", "later"}


@dataclass(frozen=True)
class SnapshotRecord:
    id: int
    created_at: datetime
    source_counts: dict[str, int]
    signals: list[Signal]
    source: str
    status: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class TaskRecord:
    id: int
    snapshot_id: int | None
    source: str
    priority_bucket: str
    title: str
    action_hint: str
    status: str
    due_at: datetime | None
    url: str
    manual: bool
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class ActionRunRecord:
    run_id: str
    task_id: int | None
    action_type: str
    status: str
    started_at: datetime
    finished_at: datetime | None
    request_payload: dict[str, Any]
    result_payload: dict[str, Any]
    error: str | None


@dataclass(frozen=True)
class SkillRunRecord:
    run_id: str
    skill_name: str
    status: str
    started_at: datetime
    finished_at: datetime | None
    request_payload: dict[str, Any]
    output_payload: dict[str, Any]
    error: str | None


class Storage:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    source_counts_json TEXT NOT NULL,
                    signals_json TEXT NOT NULL,
                    source TEXT NOT NULL,
                    status TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    snapshot_id INTEGER NULL REFERENCES snapshots(id) ON DELETE CASCADE,
                    source TEXT NOT NULL,
                    priority_bucket TEXT NOT NULL,
                    title TEXT NOT NULL,
                    action_hint TEXT NOT NULL,
                    status TEXT NOT NULL,
                    due_at TEXT NULL,
                    url TEXT NOT NULL DEFAULT '',
                    manual INTEGER NOT NULL DEFAULT 0,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS action_runs (
                    run_id TEXT PRIMARY KEY,
                    task_id INTEGER NULL REFERENCES tasks(id) ON DELETE SET NULL,
                    action_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT NULL,
                    request_payload_json TEXT NOT NULL DEFAULT '{}',
                    result_payload_json TEXT NOT NULL DEFAULT '{}',
                    error TEXT NULL
                );

                CREATE TABLE IF NOT EXISTS skill_runs (
                    run_id TEXT PRIMARY KEY,
                    skill_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT NULL,
                    request_payload_json TEXT NOT NULL DEFAULT '{}',
                    output_payload_json TEXT NOT NULL DEFAULT '{}',
                    error TEXT NULL
                );

                CREATE TABLE IF NOT EXISTS refresh_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    status TEXT NOT NULL,
                    message TEXT NOT NULL DEFAULT ''
                );
                """
            )
            # Lightweight migration for existing DBs created before metadata_json was added.
            columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(snapshots)").fetchall()
            }
            if "metadata_json" not in columns:
                conn.execute(
                    "ALTER TABLE snapshots ADD COLUMN metadata_json TEXT NOT NULL DEFAULT '{}'"
                )
            conn.commit()

    def insert_snapshot(
        self,
        signals: list[Signal],
        source_counts: dict[str, int],
        *,
        created_at: datetime | None = None,
        source: str = "scheduled",
        status: str = "ready",
        metadata: dict[str, Any] | None = None,
    ) -> int:
        ts = (created_at or datetime.now(tz=timezone.utc)).isoformat()
        signals_json = json.dumps([signal_to_dict(item) for item in signals], ensure_ascii=False)
        counts_json = json.dumps(source_counts, ensure_ascii=False)
        metadata_json = json.dumps(metadata or {}, ensure_ascii=False)
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO snapshots(created_at, source_counts_json, signals_json, source, status, metadata_json)
                VALUES(?, ?, ?, ?, ?, ?)
                """,
                (ts, counts_json, signals_json, source, status, metadata_json),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def replace_auto_tasks_for_snapshot(self, snapshot_id: int, tasks: list[dict[str, Any]]) -> None:
        now = datetime.now(tz=timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute("DELETE FROM tasks WHERE snapshot_id = ? AND manual = 0", (snapshot_id,))
            for task in tasks:
                priority_bucket = str(task.get("priority_bucket", "later"))
                if priority_bucket not in PRIORITY_BUCKETS:
                    priority_bucket = "later"
                status = str(task.get("status", "todo"))
                if status not in TASK_STATUSES:
                    status = "todo"
                due_at = task.get("due_at")
                due_at_text = None
                if due_at:
                    due_at_text = str(due_at)
                conn.execute(
                    """
                    INSERT INTO tasks(
                        snapshot_id, source, priority_bucket, title, action_hint, status,
                        due_at, url, manual, metadata_json, created_at, updated_at
                    )
                    VALUES(?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)
                    """,
                    (
                        snapshot_id,
                        str(task.get("source", "unknown")),
                        priority_bucket,
                        str(task.get("title", "")),
                        str(task.get("action_hint", "")),
                        status,
                        due_at_text,
                        str(task.get("url", "")),
                        json.dumps(task.get("metadata", {}), ensure_ascii=False),
                        now,
                        now,
                    ),
                )
            conn.commit()

    def get_latest_snapshot(self) -> SnapshotRecord | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM snapshots ORDER BY created_at DESC LIMIT 1").fetchone()
        if row is None:
            return None
        payload = json.loads(row["signals_json"])
        signals = [signal_from_dict(item) for item in payload]
        return SnapshotRecord(
            id=int(row["id"]),
            created_at=parse_timestamp(row["created_at"]),
            source_counts={k: int(v) for k, v in json.loads(row["source_counts_json"]).items()},
            signals=signals,
            source=str(row["source"]),
            status=str(row["status"]),
            metadata=dict(json.loads(row["metadata_json"] or "{}")),
        )

    def get_latest_snapshot_created_at(self) -> datetime | None:
        with self._connect() as conn:
            row = conn.execute("SELECT created_at FROM snapshots ORDER BY created_at DESC LIMIT 1").fetchone()
        if row is None:
            return None
        return parse_timestamp(row["created_at"])

    def list_board_tasks(self, latest_snapshot_id: int | None) -> list[TaskRecord]:
        order_sql = """
            CASE priority_bucket WHEN 'now' THEN 0 WHEN 'next' THEN 1 ELSE 2 END,
            CASE status WHEN 'in_progress' THEN 0 WHEN 'todo' THEN 1 WHEN 'snoozed' THEN 2 ELSE 3 END,
            COALESCE(due_at, updated_at),
            id
        """
        with self._connect() as conn:
            if latest_snapshot_id is None:
                rows = conn.execute(
                    f"""
                    SELECT * FROM tasks
                    WHERE manual = 1 AND status != 'done'
                    ORDER BY {order_sql}
                    """
                ).fetchall()
            else:
                rows = conn.execute(
                    f"""
                    SELECT * FROM tasks
                    WHERE (snapshot_id = ? AND manual = 0) OR (manual = 1 AND status != 'done')
                    ORDER BY {order_sql}
                    """,
                    (latest_snapshot_id,),
                ).fetchall()
        return [self._task_from_row(row) for row in rows]

    def get_task(self, task_id: int) -> TaskRecord | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            return None
        return self._task_from_row(row)

    def create_manual_task(
        self,
        title: str,
        action_hint: str,
        *,
        priority_bucket: str = "next",
        url: str = "",
        due_at: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        if priority_bucket not in PRIORITY_BUCKETS:
            priority_bucket = "next"
        created = datetime.now(tz=timezone.utc).isoformat()
        snapshot = self.get_latest_snapshot()
        snapshot_id = snapshot.id if snapshot else None
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO tasks(
                    snapshot_id, source, priority_bucket, title, action_hint, status,
                    due_at, url, manual, metadata_json, created_at, updated_at
                )
                VALUES(?, 'manual', ?, ?, ?, 'todo', ?, ?, 1, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    priority_bucket,
                    title,
                    action_hint,
                    due_at,
                    url,
                    json.dumps(metadata or {}, ensure_ascii=False),
                    created,
                    created,
                ),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def update_task_status(self, task_id: int, status: str) -> None:
        if status not in TASK_STATUSES:
            raise ValueError(f"Unsupported task status: {status}")
        updated_at = datetime.now(tz=timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                "UPDATE tasks SET status = ?, updated_at = ? WHERE id = ?",
                (status, updated_at, task_id),
            )
            conn.commit()

    def create_action_run(self, task_id: int | None, action_type: str, request_payload: dict[str, Any]) -> str:
        run_id = uuid.uuid4().hex
        started_at = datetime.now(tz=timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO action_runs(
                    run_id, task_id, action_type, status, started_at, request_payload_json
                )
                VALUES(?, ?, ?, 'queued', ?, ?)
                """,
                (run_id, task_id, action_type, started_at, json.dumps(request_payload, ensure_ascii=False)),
            )
            conn.commit()
        return run_id

    def update_action_run(
        self,
        run_id: str,
        *,
        status: str,
        result_payload: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        finished_at = None
        if status in {"completed", "failed"}:
            finished_at = datetime.now(tz=timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE action_runs
                SET status = ?,
                    finished_at = COALESCE(?, finished_at),
                    result_payload_json = ?,
                    error = ?
                WHERE run_id = ?
                """,
                (
                    status,
                    finished_at,
                    json.dumps(result_payload or {}, ensure_ascii=False),
                    error,
                    run_id,
                ),
            )
            conn.commit()

    def get_action_run(self, run_id: str) -> ActionRunRecord | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM action_runs WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            return None
        return self._action_run_from_row(row)

    def list_recent_action_runs(self, limit: int = 20) -> list[ActionRunRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM action_runs ORDER BY started_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._action_run_from_row(row) for row in rows]

    def create_skill_run(self, skill_name: str, request_payload: dict[str, Any]) -> str:
        run_id = uuid.uuid4().hex
        started_at = datetime.now(tz=timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO skill_runs(
                    run_id, skill_name, status, started_at, request_payload_json
                )
                VALUES(?, ?, 'queued', ?, ?)
                """,
                (run_id, skill_name, started_at, json.dumps(request_payload, ensure_ascii=False)),
            )
            conn.commit()
        return run_id

    def update_skill_run(
        self,
        run_id: str,
        *,
        status: str,
        output_payload: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        finished_at = None
        if status in {"completed", "failed"}:
            finished_at = datetime.now(tz=timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE skill_runs
                SET status = ?,
                    finished_at = COALESCE(?, finished_at),
                    output_payload_json = ?,
                    error = ?
                WHERE run_id = ?
                """,
                (
                    status,
                    finished_at,
                    json.dumps(output_payload or {}, ensure_ascii=False),
                    error,
                    run_id,
                ),
            )
            conn.commit()

    def get_skill_run(self, run_id: str) -> SkillRunRecord | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM skill_runs WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            return None
        return self._skill_run_from_row(row)

    def list_recent_skill_runs(self, limit: int = 20) -> list[SkillRunRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM skill_runs ORDER BY started_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._skill_run_from_row(row) for row in rows]

    def record_refresh_event(self, *, kind: str, status: str, message: str = "") -> None:
        created_at = datetime.now(tz=timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO refresh_events(created_at, kind, status, message)
                VALUES(?, ?, ?, ?)
                """,
                (created_at, kind, status, message),
            )
            conn.commit()

    def get_last_refresh_event(self) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM refresh_events ORDER BY created_at DESC LIMIT 1").fetchone()
        if row is None:
            return None
        return {
            "id": int(row["id"]),
            "created_at": parse_timestamp(row["created_at"]),
            "kind": str(row["kind"]),
            "status": str(row["status"]),
            "message": str(row["message"]),
        }

    def can_refresh_now(self, cooldown_minutes: int) -> tuple[bool, datetime | None]:
        last = self.get_last_refresh_event()
        if last is None:
            return True, None
        if last["status"] == "failed":
            return True, None
        next_allowed = last["created_at"] + timedelta(minutes=cooldown_minutes)
        if datetime.now(tz=timezone.utc) >= next_allowed:
            return True, next_allowed
        return False, next_allowed

    def cleanup_old(self, retention_days: int) -> None:
        cutoff = (datetime.now(tz=timezone.utc) - timedelta(days=retention_days)).isoformat()
        with self._connect() as conn:
            conn.execute("DELETE FROM snapshots WHERE created_at < ?", (cutoff,))
            conn.execute("DELETE FROM action_runs WHERE started_at < ?", (cutoff,))
            conn.execute("DELETE FROM skill_runs WHERE started_at < ?", (cutoff,))
            conn.execute("DELETE FROM refresh_events WHERE created_at < ?", (cutoff,))
            conn.execute(
                "DELETE FROM tasks WHERE manual = 1 AND updated_at < ? AND status = 'done'",
                (cutoff,),
            )
            conn.commit()

    def _task_from_row(self, row: sqlite3.Row) -> TaskRecord:
        due_at = parse_timestamp(row["due_at"]) if row["due_at"] else None
        return TaskRecord(
            id=int(row["id"]),
            snapshot_id=int(row["snapshot_id"]) if row["snapshot_id"] is not None else None,
            source=str(row["source"]),
            priority_bucket=str(row["priority_bucket"]),
            title=str(row["title"]),
            action_hint=str(row["action_hint"]),
            status=str(row["status"]),
            due_at=due_at,
            url=str(row["url"]),
            manual=bool(row["manual"]),
            metadata=dict(json.loads(row["metadata_json"])),
            created_at=parse_timestamp(row["created_at"]),
            updated_at=parse_timestamp(row["updated_at"]),
        )

    def _action_run_from_row(self, row: sqlite3.Row) -> ActionRunRecord:
        finished_at = parse_timestamp(row["finished_at"]) if row["finished_at"] else None
        return ActionRunRecord(
            run_id=str(row["run_id"]),
            task_id=int(row["task_id"]) if row["task_id"] is not None else None,
            action_type=str(row["action_type"]),
            status=str(row["status"]),
            started_at=parse_timestamp(row["started_at"]),
            finished_at=finished_at,
            request_payload=dict(json.loads(row["request_payload_json"])),
            result_payload=dict(json.loads(row["result_payload_json"])),
            error=str(row["error"]) if row["error"] else None,
        )

    def _skill_run_from_row(self, row: sqlite3.Row) -> SkillRunRecord:
        finished_at = parse_timestamp(row["finished_at"]) if row["finished_at"] else None
        return SkillRunRecord(
            run_id=str(row["run_id"]),
            skill_name=str(row["skill_name"]),
            status=str(row["status"]),
            started_at=parse_timestamp(row["started_at"]),
            finished_at=finished_at,
            request_payload=dict(json.loads(row["request_payload_json"])),
            output_payload=dict(json.loads(row["output_payload_json"])),
            error=str(row["error"]) if row["error"] else None,
        )
