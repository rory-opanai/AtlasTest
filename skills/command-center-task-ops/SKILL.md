---
name: command-center-task-ops
description: Use when the user wants a high-leverage execution plan from the current command-center board (Now/Next/Later) and suggested actions to run first.
---

# Command Center Task Ops

## Overview
Turn the latest dashboard task state into an execution sequence for the next 2-4 hours. Focus on time-critical items and actionable drafts.

## Workflow
1. Export current board state:
```bash
python3 skills/command-center-task-ops/scripts/task_ops.py
```
2. Build an execution plan with:
- `Start now` tasks (top 3)
- `Queue next` tasks (next 3)
- `Defer` tasks
- Suggested action buttons to run (draft Slack/email/prep brief)

3. Keep output concise:
- What to do first (single item)
- Why it is first (deadline/risk/customer impact)
- Exact draft or command to execute

## Priority Rules
- Favor tasks with `due_at` in the next 2 hours.
- Favor Slack/Gmail tasks that include direct request or urgent signals.
- Do not include completed tasks.

## References
- Execution template: `references/execution-template.md`
