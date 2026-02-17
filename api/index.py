from __future__ import annotations

import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# Vercel serverless runtime has writable /tmp only.
os.environ.setdefault("FLIGHT_DECK_DB_PATH", "/tmp/flight_deck.db")
os.environ.setdefault("FLIGHT_DECK_SNAPSHOT_PATH", "/tmp/latest_snapshot.json")

from daily_flight_deck.dashboard_app import create_app


app = create_app(config_path=str(ROOT / "config" / "daily_flight_deck.yaml"), start_workers=False)
