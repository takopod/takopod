---
name: schedule
description: Create, list, pause, resume, or delete recurring scheduled tasks
user_invocable: true
always_enabled: true
---

Use your `mcp__schedule__*` tools to manage recurring tasks.

## Creating a schedule

Ask the user for: what to do, how often, and confirm before creating.

Call `mcp__schedule__create_schedule` with:
- `prompt`: A self-contained instruction. Include all context (URLs, channel names, criteria, actions). The executor has no conversation history.
- `interval_minutes`: Minimum 5. Suggest reasonable defaults (e.g., 30 for monitoring, 60 for digests, 1440 for daily).
- `allowed_tools`: Omit unless the user specifies tool restrictions.

## Other operations

- `mcp__schedule__list_schedules` — list all (optionally filter by `status`: "active"/"paused")
- `mcp__schedule__get_schedule` — get details + last result by `task_id`
- `mcp__schedule__update_schedule` — change prompt, interval, or allowed_tools
- `mcp__schedule__pause_schedule` / `mcp__schedule__resume_schedule` — toggle execution
- `mcp__schedule__delete_schedule` — permanent removal

Always show the `task_id` to the user after create/update/delete so they can reference it later.
