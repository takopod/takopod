---
name: quay-sdlc
description: "Multi-agent SDLC: scan Jira for labeled tickets, triage and implement fixes via sub-agent delegation — agents coordinate via shared SQLite DB"
shared_data: true
---

# Quay SDLC

Multi-agent pipeline for `takopod`-labeled Jira tickets. Agents share a SQLite DB at `/workspace/shared/quay-sdlc/sdlc.db`. All DB operations go through `db.py`.

## Setup

When the user asks to "set up quay-sdlc" and specifies a role (scanner, triager, or coder), read `/workspace/.claude/skills/quay-sdlc/sdlc-setup.md` and follow the instructions.

## Workflows

- `workflow-scanner.md` — scan Jira, record new tickets
- `workflow-triager.md` — triage tickets via ssd sub-agent, comment on Jira
- `workflow-coder.md` — implement fixes via sub-agent delegation, create PRs

## Schedules

**Scanner**: prompt: `use quay-sdlc skill as a scanner` | interval_minutes: 5

**Triager**: prompt: `use quay-sdlc skill as a triager` | interval_minutes: 10

**Coder**: prompt: `use quay-sdlc skill as a coder` | interval_minutes: 30
