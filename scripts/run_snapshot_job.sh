#!/bin/zsh
set -euo pipefail

ROOT="/Users/roryh/Documents/Rorys Dashboard"
cd "$ROOT"

mkdir -p "$ROOT/data"
export PYTHONPATH="$ROOT/src"

python3 -m daily_flight_deck.snapshot_producer \
  --config "$ROOT/config/daily_flight_deck.yaml" \
  --source scheduled
