---
name: command-center-integration-audit
description: Use when the user asks why the command center is empty, stale, or not pulling Slack/Gmail/Calendar correctly. Runs a deterministic ingestion audit and returns concrete remediation steps.
---

# Command Center Integration Audit

## Overview
Run this skill for data-quality triage on the SE Daily Command Center. It validates the latest snapshot, source counts, connector diagnostics, and recent refresh failures.

## Workflow
1. Run one fresh snapshot pull:
```bash
./scripts/run_snapshot_job.sh
```
2. Run the audit script:
```bash
python3 skills/command-center-integration-audit/scripts/audit_snapshot.py
```
3. Summarize findings in this order:
- Snapshot freshness and fetch mode
- Slack/Gmail/Calendar raw vs in-scope vs actionable counts
- Last 5 refresh events (with failures)
- Most likely root cause
- Exact next fix commands

## Interpretation Rules
- If `raw_counts` are all zero: connector/tool access issue.
- If Slack `raw_count > 0` and `in_scope_raw_count == 0`: Slack query mismatch (not channel-scoped enough).
- If `raw_count > 0` and `actionable_count == 0`: normalization/ranking filtered everything.
- If the newest refresh event is `failed`: include the failure message verbatim and prioritize that fix.

## References
- Remediation checklist: `references/remediation-checklist.md`
