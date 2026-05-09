# Slack Thread Monitoring UI

## Problem

When an agent responds to a Slack message, the thread is auto-registered for ongoing polling (`slack_active_threads` table). Over time, agents accumulate monitored threads with no visibility in the UI. There is no way to see which threads an agent is following, how many there are, or remove stale ones.

## Current State

- **API exists**: `GET /api/slack/threads` returns all monitored threads with channel ID, thread timestamp, agent name, and creation time. `POST /api/slack/threads` adds a thread. `DELETE /api/slack/threads/{id}` removes one.
- **Auto-registration**: When the orchestrator posts a Slack reply (`orchestrator/ipc.py:573-585`), it inserts into `slack_active_threads` via `INSERT OR IGNORE`.
- **Auto-expiry**: Threads older than `slack_thread_ttl_days` (default 7 days) are pruned on each poller tick (`orchestrator/slack_poller.py:262-269`).
- **Backoff**: Idle threads double their poll interval up to 6 hours (`THREAD_MAX_INTERVAL`). Active threads reset to 10 seconds.
- **No frontend**: The Slack settings view (`web/src/components/slack-view.tsx`) shows polling channels and the thread TTL setting, but does not display or manage active threads.

## Tasks

### 1. Show monitored threads in the Slack settings view

Add a section to `slack-view.tsx` that lists all active threads from `GET /api/slack/threads`. Each row should show:

- Agent name
- Channel ID (ideally resolved to channel name if available)
- Thread creation date / last activity
- A delete button that calls `DELETE /api/slack/threads/{id}`

### 2. Per-agent thread count

Show a thread count indicator on the agent card or agent detail view so users can see at a glance how many threads each agent is monitoring. The data is already available — just needs a query filtered by `agent_id`.

### 3. Bulk cleanup

Add a "Remove all expired" or "Remove all for agent" action. Currently the TTL-based pruning handles old threads, but there's no manual bulk cleanup option.

## Relevant Files

- `orchestrator/slack_routes.py` — existing CRUD endpoints (lines 362-434)
- `orchestrator/slack_poller.py` — polling loop, auto-expiry, backoff logic
- `orchestrator/ipc.py` — auto-registration on reply (lines 573-585)
- `web/src/components/slack-view.tsx` — Slack settings UI (thread TTL config exists here)
