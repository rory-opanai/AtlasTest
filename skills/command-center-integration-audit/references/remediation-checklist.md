# Integration Remediation Checklist

1. Verify Codex connectors are enabled for exec runs (`--enable connectors`).
2. Confirm `~/.codex/config.toml` includes `codex_apps` (or dedicated Slack/Gmail/Calendar MCP servers).
3. Run `./scripts/run_snapshot_job.sh` and inspect latest `refresh_events`.
4. If Slack raw > 0 but in-scope = 0, tighten channel-targeting queries.
5. If all sources are zero, re-auth connector sessions in Codex.
6. Keep `FLIGHT_DECK_ALLOW_EMPTY_SNAPSHOT` unset unless a truly empty day is expected.
