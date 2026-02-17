---
name: se-daily-flight-deck
description: Build and deliver a weekday SE morning brief from Slack, Google Calendar, and Gmail using a deterministic scoring rubric, then post to Slack webhook with Gmail fallback on failure.
---

# SE Daily Flight Deck

Use this skill when asked to generate or maintain the SE Daily Flight Deck briefing workflow.

## Workflow

1. Load config from `config/daily_flight_deck.yaml`.
2. Fetch source data in this order: Slack, Calendar, Gmail.
3. Normalize all items into a common schema.
4. Score with the fixed rubric:
   - `+50` due/meeting within 2h
   - `+35` direct request
   - `+25` escalation/urgent keyword
   - `+20` unanswered action request
   - `-20` low-signal promotional pattern
5. Render exact required sections:
   - `Top 5 Actions for Today`
   - `Time-Critical in Next 2 Hours`
   - `Calendar Collisions / Prep Needed`
   - `Inbox Watchlist (Last 24h)`
   - `Deferred / Low Priority`
   - `One Recommended First Task (start here)`
6. Deliver to Slack webhook, then fallback to Gmail send on webhook failure.

## Local implementation references

- Engine package: `src/daily_flight_deck/`
- Automation prompt template: `prompts/se_daily_flight_deck_prompt.md`
- CLI: `python3 -m daily_flight_deck.cli --config config/daily_flight_deck.yaml ...`

## Guardrails

- Do not include GitHub or Jira in v1.
- Do not create tasks or calendar blocks automatically.
- Keep the brief scannable within five minutes.
