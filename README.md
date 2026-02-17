# SE Daily Command Center

Local dashboard command center for daily SE execution. It keeps the same source/schedule logic as Daily Flight Deck, then exposes a richer local UI at `http://localhost:2025`.

## What it includes

- Existing normalize/score/render engine for Slack + Calendar + Gmail.
- FastAPI + Jinja + HTMX dashboard at `localhost:2025`.
- SQLite state for snapshots, tasks, action runs, and skill runs.
- Weekday `7:30` snapshot producer (`codex exec` -> MCP -> stored snapshot).
- Action buttons powered by OpenAI Responses API + local tool registry.
- Allowlisted skill runner buttons:
  - `se-daily-flight-deck`
  - `gh-fix-ci`
  - `gh-address-comments`
  - `incident-report-generator`

## Local run

```bash
./scripts/run_dashboard.sh
```

Then open:

- `http://localhost:2025`

In the UI, check `Source Ingestion Health` to verify pull status:
- `Raw Fetched`: number fetched from source payload.
- `Actionable`: number that survived scoring/window filters.
- `Fetch mode`: `codex_exec` (live) vs `input_json` (fixture/manual input).

## Manual snapshot run

```bash
./scripts/run_snapshot_job.sh
```

You can also bypass codex fetch with fixture payload:

```bash
PYTHONPATH=src python3 -m daily_flight_deck.snapshot_producer \
  --config config/daily_flight_deck.yaml \
  --source manual \
  --input-json tests/fixtures/full_snapshot_payload.json
```

## Environment variables

- `OPENAI_API_KEY`: enables live Responses API action generation.
- `OPENAI_MODEL`: optional override for model used by action engine.
- `runtime.codex_exec_model` in config controls model used by snapshot ingestion via `codex exec`.
- `FLIGHT_DECK_ALLOW_EMPTY_SNAPSHOT`: optional (`1/true/yes`) to allow all-zero source payloads.
- `SLACK_WEBHOOK_URL`: used by legacy CLI posting flow.
- `BRIEF_FALLBACK_EMAIL`: fallback destination for email metadata.

## launchd scheduler template

Template file:

- `src/daily_flight_deck/scheduler_templates/com.rory.daily-flight-deck.plist`

Install flow (manual):

1. Copy plist to `~/Library/LaunchAgents/com.rory.daily-flight-deck.plist`
2. `launchctl load ~/Library/LaunchAgents/com.rory.daily-flight-deck.plist`
3. `launchctl start com.rory.daily-flight-deck`

## Important connector requirement

The scheduled snapshot runner uses `codex exec`. Your local Codex CLI must have MCP server access to Slack/Gmail/Google Calendar.

If `~/.codex/config.toml` does not include `codex_apps` (or dedicated `slack`/`gmail`/`google_calendar` MCP entries), refresh jobs will be marked failed in the dashboard.

If refresh runs but returns zero items for all three sources, the run is also marked failed by default (to avoid silently storing mock-looking snapshots). Set `FLIGHT_DECK_ALLOW_EMPTY_SNAPSHOT=1` only when an empty day is expected.
