Fetch Daily Flight Deck source payloads from connected MCP/App tools.

Hard rules:
- Sources: Slack + Google Calendar + Gmail only.
- Do not include GitHub, Jira, or synthetic/mock/example data.
- Return JSON only (no prose).
- If a tool is unavailable, do not fabricate data. Report it in diagnostics.
- Keep tool-call budget small:
  - Slack: at most 8 search calls
  - Calendar: at most 1 search call
  - Gmail: at most 1 fetch/search call

Source queries:
- Slack window: last 24 hours, channels constrained to allowlist/prefix list.
  - First run one broad query: `after:{slack_after_date}`.
  - If that broad query appears not to include allowlisted channels, run targeted follow-ups using channel filters:
    `after:{slack_after_date} in:#<channel>`.
  - Prioritize targeted channels in this order when follow-up calls are needed:
    `gtm-se-requests`, `gtm-se`, `chatgpt-bug-escalation`, `customer-incidents`, `codex-app-feedback`, `codex-gtm`, `api-scale-tier`.
  - Stop targeted calls once any allowlisted results are found or budget is exhausted.
  - Deduplicate Slack rows by `message_info_str` or (`web_link`,`message_ts`).
  - If available, use `slack_search(query=<value>, topn<=120)`.
- Calendar window: next 24 hours.
  - Use `calendar_time_min` and `calendar_time_max` if provided.
  - If available, use `google_calendar_search_events(time_min, time_max, max_results<=60)`.
- Gmail window: last 24 hours.
  - Prefer one recent-emails call, then keep only rows in the 24h window.
  - If available, use `gmail_get_recent_emails(top_k<=80)`.

Required output JSON shape:
{
  "slack_results": [ ...raw rows... ],
  "calendar_events": [ ...raw rows... ],
  "gmail_emails": [ ...raw rows... ],
  "diagnostics": {
    "tool_access": {
      "slack": "ok|unavailable",
      "calendar": "ok|unavailable",
      "gmail": "ok|unavailable"
    },
    "query_windows": {
      "slack_hours": 24,
      "calendar_hours": 24,
      "gmail_hours": 24
    },
    "errors": [ "...optional source-specific errors..." ]
  }
}

Preserve raw tool field names where possible so downstream normalizers can parse fields directly.

Runtime variables available:
- `slack_channels_exact_csv`
- `slack_channels_prefix_csv`
