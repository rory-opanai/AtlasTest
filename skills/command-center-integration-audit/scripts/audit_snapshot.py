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


def main() -> int:
    if not DB_PATH.exists():
        print(json.dumps({"error": f"Database not found at {DB_PATH}"}, indent=2))
        return 1

    with _connect() as conn:
        snapshot = conn.execute(
            "SELECT id, created_at, source, status, source_counts_json, metadata_json "
            "FROM snapshots ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        refresh_rows = conn.execute(
            "SELECT created_at, kind, status, message "
            "FROM refresh_events ORDER BY created_at DESC LIMIT 5"
        ).fetchall()

    if snapshot is None:
        print(json.dumps({"error": "No snapshots found"}, indent=2))
        return 1

    source_counts = json.loads(snapshot["source_counts_json"] or "{}")
    metadata = json.loads(snapshot["metadata_json"] or "{}")

    payload = {
        "snapshot": {
            "id": int(snapshot["id"]),
            "created_at": snapshot["created_at"],
            "source": snapshot["source"],
            "status": snapshot["status"],
            "fetch_mode": metadata.get("fetch_mode"),
        },
        "counts": {
            "raw": metadata.get("raw_counts", {}),
            "in_scope_raw": metadata.get("in_scope_raw_counts", {}),
            "actionable": source_counts,
        },
        "diagnostics": metadata.get("diagnostics", {}),
        "slack_channel_stats": metadata.get("slack_channel_stats", {}),
        "recent_refresh_events": [
            {
                "created_at": row["created_at"],
                "kind": row["kind"],
                "status": row["status"],
                "message": row["message"],
            }
            for row in refresh_rows
        ],
    }

    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
