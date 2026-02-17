#!/bin/zsh
set -euo pipefail

ROOT="/Users/roryh/Documents/Rorys Dashboard"
cd "$ROOT"

export PYTHONPATH="$ROOT/src"

HOST="127.0.0.1"
PORT="2025"

exec python3 -m uvicorn daily_flight_deck.dashboard_app:app --host "$HOST" --port "$PORT"
