---
name: schedule
description: Create, list, pause, resume, or delete scheduled tasks — interval, file watch, webhook, GitHub PR/issues, or Slack channel triggers
user_invocable: true
always_enabled: true
---

Use your `mcp__schedule__*` tools to manage scheduled tasks.

## Creating a schedule

Call `mcp__schedule__create_schedule` with:
- `prompt`: A self-contained instruction. Include all context (URLs, channel names, criteria, actions). The executor has no conversation history.
- `trigger_type`: See trigger types below. Defaults to `interval` if omitted.
- `allowed_tools`: Omit unless the user specifies tool restrictions.

Always show the `task_id` after create/update/delete so the user can reference it later.

---

## Trigger types

### `interval` — run on a timer
- `interval_minutes`: required, minimum 5. Defaults: 30 (monitoring), 60 (digests), 1440 (daily).

**Idle backoff** (optional — doubles interval when no activity is found, up to a max):
- `base_interval_minutes`: fastest polling interval
- `max_interval_minutes`: ceiling for backoff. Call `signal_activity` to reset.

**One-time tasks** (e.g. "do X at 6am tomorrow"):
- Calculate minutes from now to target time, set that as `interval_minutes`
- Note to the user that this recurs — they must delete it after it fires once
- Include a reminder in the prompt itself: "This is a one-time task — delete or pause this schedule after completing."

### `file_watch` — run when new files appear in a directory
- `watch_dir`: relative path within `/workspace` (e.g. `inbox`)

### `webhook` — run when an HTTP POST is received
- No extra params required; the scheduler provides a webhook URL on creation

### `github_pr` — poll a GitHub PR for new comments, reviews, or commits
- `github_repo`: `owner/repo` format (required)
- `github_pr_number`: specific PR to watch; omit to watch all open PRs
- `github_labels`: filter by labels (optional)
- `github_state`: `open` (default), `closed`, or `all`

### `github_issues` — poll repo issues
- `github_repo`: `owner/repo` format (required)
- `github_labels`: filter by labels (optional)
- `github_state`: `open` (default), `closed`, or `all`

### `slack_channel` — observe a Slack channel for new messages
- `slack_channel_id`: channel ID, e.g. `C1234567890` (required)
- `slack_channel_name`: human-readable name for display (optional)

---

## Other operations

- `mcp__schedule__list_schedules` — list all (optionally filter by `status`: "active"/"paused")
- `mcp__schedule__get_schedule` — get details + last result by `task_id`
- `mcp__schedule__update_schedule` — change prompt, interval, or allowed_tools
- `mcp__schedule__pause_schedule` / `mcp__schedule__resume_schedule` — toggle execution
- `mcp__schedule__delete_schedule` — permanent removal

---

## Gotchas

- **Interval schedules recur forever** — for one-time tasks, always warn the user and embed a self-delete reminder in the prompt.
- **No native "run at time X" support** — approximate by computing minutes-from-now to the target time.
- The executor has **no conversation history** — the `prompt` must be fully self-contained with all context (issue keys, usernames, URLs, etc.).
