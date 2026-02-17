# SE Daily Flight Deck Runbook

Use this runbook for weekday morning briefing.

## Inputs

- Config: `config/daily_flight_deck.yaml`
- Env:
  - `SLACK_WEBHOOK_URL` (required)
  - `BRIEF_FALLBACK_EMAIL` (optional, default `roryh@openai.com`)

## Hard constraints

- Sources: Slack + Google Calendar + Gmail only
- Exclude GitHub and Jira
- Read-only recommendations only
- Use full-detail snippets (no redaction)
- Keep output readable in 5 minutes

## Source fetch order

1. Slack (`mcp__codex_apps__slack_search`)
2. Calendar (`mcp__codex_apps__google_calendar_search_events`)
3. Gmail (`mcp__codex_apps__gmail_search_emails`)

## Slack query strategy

- Time window: last 24 hours
- Pull by channel allowlist and prefixes from config
- Capture messages with implied actions:
  - direct requests
  - questions needing response
  - urgent/escalation language

## Calendar query strategy

- Time window: next 24 hours
- Include upcoming meeting prep needs
- Detect collisions (overlapping events)

## Gmail query strategy

- Time window: last 24 hours
- Include all inbox items (work + non-work)

## Normalized schema

Every item should include:

- `source`
- `id/url`
- `channel_or_sender`
- `title`
- `snippet`
- `timestamp`
- `urgency_signals`
- `recommended_action`

## Scoring rubric

- `+50` due/meeting within 2h
- `+35` direct request to Rory
- `+25` escalation/incident/urgent terms
- `+20` unanswered action request
- `-20` low-signal promotional pattern

Sort descending by score, then earliest timestamp.

## Output format (exact sections)

1. `Top 5 Actions for Today`
2. `Time-Critical in Next 2 Hours`
3. `Calendar Collisions / Prep Needed`
4. `Inbox Watchlist (Last 24h)`
5. `Deferred / Low Priority`
6. `One Recommended First Task (start here)`

## Delivery

1. Build brief markdown.
2. Post brief to `SLACK_WEBHOOK_URL`.
3. If webhook post fails, send same brief through `mcp__codex_apps__gmail_send_email` to `BRIEF_FALLBACK_EMAIL` with subject `SE Daily Flight Deck - Fallback`.
4. Return a short status summary including:
   - item counts per source
   - top recommended first task
   - delivery result (Slack success/failure + fallback email status)
