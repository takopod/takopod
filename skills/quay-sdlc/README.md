# quay-sdlc

Multi-agent SDLC pipeline that automates Jira ticket processing for the Quay container registry project. Three agents coordinate through a shared SQLite database to scan, triage, and implement fixes.

## How it works

Agents share a SQLite database via a mounted directory at `/workspace/shared/quay-sdlc/`. The `shared_data: true` flag in SKILL.md tells the orchestrator to create this mount when the agent's container starts. All agents with this skill read and write to the same `sdlc.db` file.

Each agent runs a different workflow on a schedule:

- **Scanner** (every 5 minutes): Searches Jira for tickets with the `takopod` label. New tickets are inserted into the shared DB with status `new`. Duplicates are silently skipped. Does not triage or comment.

- **Triager** (every 10 minutes): Picks one `new` ticket from the DB, claims it by transitioning to `triaging`, then delegates triage to the ssd sub-agent via the Agent tool. Valid tickets move to `triaged` with a Jira comment summarizing findings. Invalid tickets move to `invalid` with a Jira comment explaining why.

- **Coder** (every 30 minutes): Picks the highest-priority `triaged` ticket, claims it as `assigned`, then delegates to sub-agents (pse, ssd, qe, etc.) via the Agent tool following the bugfix or feature workflow. On success, moves to `done` and comments the PR link on Jira. On failure, moves to `failed` with a reason.

## Ticket lifecycle

```
new -> triaging -> triaged -> assigned -> done
                -> invalid
                                       -> failed -> triaged (retry)
```

Status transitions are atomic (compare-and-swap). If two agents try to claim the same ticket, one succeeds and the other gets an error and moves on. The `ticket_log` table records every transition for auditing.

## Required skills per agent

- Scanner: `jira`, `quay-sdlc`
- Triager: `jira`, `quay-sdlc`
- Coder: `jira`, `quay-sdlc`

## Setup

1. Upload this skill to takopod (copy to `data/skills/quay-sdlc/` or use the UI)
2. Assign skills to each agent (see required skills above)
3. Restart each agent's container so the shared mount is applied
4. Tell each agent to set up its role:

**Scanner agent:**
> set up quay-sdlc as scanner

**Triager agent:**
> set up quay-sdlc as triager

**Coder agent:**
> set up quay-sdlc as coder

Each agent checks the shared mount exists, initializes the DB, and creates its own schedule.

## Files

- `SKILL.md` — Skill frontmatter and setup instructions (loaded into agent system prompt)
- `sdlc-setup.md` — Setup procedure read on demand when user asks to set up a role
- `workflow-scanner.md` — Scanner workflow instructions
- `workflow-triager.md` — Triager workflow instructions
- `workflow-coder.md` — Coder workflow instructions
- `db.py` — SQLite CLI for all database operations (init, add, update, list, get, log)
- `README.md` — This file (not loaded into agent context)

## Shared storage

The shared mount is scoped to the skill name. Only agents with `quay-sdlc` assigned get the mount at `/workspace/shared/quay-sdlc/`. Other agents never see it. If you have separate groups of agents working on different projects, each group uses a different skill with `shared_data: true` and gets its own isolated storage.

## db.py usage

```
python db.py init                                           # create tables (idempotent)
python db.py add PROJQUAY-123 --summary "..." --priority High --issue-type Bug --url "..."
python db.py update PROJQUAY-123 triaging                   # atomic claim
python db.py update PROJQUAY-123 triaged --notes "..."      # complete triage
python db.py list --status new --limit 3                    # query by status
python db.py list --status triaged --limit 1 --sort priority
python db.py get PROJQUAY-123                               # single ticket detail
python db.py log PROJQUAY-123                               # audit trail
```

`db.py` refuses to run if the shared mount is not present, preventing silent writes to ephemeral container-local storage.
