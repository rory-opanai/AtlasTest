#!/usr/bin/env python3
from __future__ import annotations

import json
import sqlite3
from pathlib import Path


DB_PATH = Path("data/flight_deck.db")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _load_latest_snapshot_id(conn: sqlite3.Connection) -> int | None:
    row = conn.execute("SELECT id FROM snapshots ORDER BY created_at DESC LIMIT 1").fetchone()
    if row is None:
        return None
    return int(row["id"])


def _load_tasks(conn: sqlite3.Connection, snapshot_id: int | None) -> list[dict]:
    if snapshot_id is None:
        return []
    rows = conn.execute(
        """
        SELECT id, source, priority_bucket, title, action_hint, status, due_at, url, metadata_json
        FROM tasks
        WHERE ((snapshot_id = ? AND manual = 0) OR manual = 1) AND status != 'done'
        ORDER BY
          CASE priority_bucket WHEN 'now' THEN 0 WHEN 'next' THEN 1 ELSE 2 END,
          CASE status WHEN 'in_progress' THEN 0 WHEN 'todo' THEN 1 ELSE 2 END,
          COALESCE(due_at, updated_at),
          id
        """,
        (snapshot_id,),
    ).fetchall()
    items: list[dict] = []
    for row in rows:
        items.append(
            {
                "id": int(row["id"]),
                "source": str(row["source"]),
                "bucket": str(row["priority_bucket"]),
                "title": str(row["title"]),
                "action_hint": str(row["action_hint"]),
                "status": str(row["status"]),
                "due_at": row["due_at"],
                "url": str(row["url"] or ""),
                "metadata": json.loads(row["metadata_json"] or "{}"),
            }
        )
    return items


def main() -> int:
    if not DB_PATH.exists():
        print(json.dumps({"error": f"Database not found at {DB_PATH}"}, indent=2))
        return 1

    with _connect() as conn:
        snapshot_id = _load_latest_snapshot_id(conn)
        tasks = _load_tasks(conn, snapshot_id)

    grouped = {"now": [], "next": [], "later": []}
    for task in tasks:
        grouped.setdefault(task["bucket"], []).append(task)

    payload = {
        "snapshot_id": snapshot_id,
        "counts": {bucket: len(items) for bucket, items in grouped.items()},
        "start_now": grouped["now"][:3],
        "queue_next": grouped["next"][:3],
        "defer": grouped["later"][:6],
    }
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
