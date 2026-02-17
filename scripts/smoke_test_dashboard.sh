#!/bin/zsh
set -euo pipefail

ROOT="/Users/roryh/Documents/Rorys Dashboard"
cd "$ROOT"

export PYTHONPATH="$ROOT/src"

echo "[1/4] Unit tests"
PYTHONDONTWRITEBYTECODE=1 pytest -q -p no:cacheprovider

echo "[2/4] Snapshot ingest"
./scripts/run_snapshot_job.sh >/tmp/flight_deck_snapshot.out
cat /tmp/flight_deck_snapshot.out

echo "[3/4] Dashboard endpoint health"
for path in / /partials/top-strip /partials/board /partials/panels /partials/runs /api/snapshot/latest; do
  code=$(/usr/bin/curl -s -o /tmp/cc_resp.out -w "%{http_code}" "http://127.0.0.1:2025$path")
  echo "$path -> $code"
  if [[ "$code" -lt 200 || "$code" -ge 300 ]]; then
    echo "Failed on $path"
    cat /tmp/cc_resp.out
    exit 1
  fi
done

echo "[4/4] Integration audit summary"
/usr/bin/python3 skills/command-center-integration-audit/scripts/audit_snapshot.py | /usr/bin/sed -n '1,120p'

echo "Smoke test completed."
