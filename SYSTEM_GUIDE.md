# Takopod — Complete System Guide

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              YOUR BROWSER                                       │
│                         http://localhost:8000                                    │
│  ┌──────────┐  ┌──────────────────────┐  ┌──────────────────────────────────┐   │
│  │ Sidebar  │  │    Chat Area          │  │  Right Panel                    │   │
│  │ (agents) │  │    (messages,         │  │  (skills, MCP, containers,      │   │
│  │          │  │     tool calls,       │  │   file browser)                 │   │
│  │          │  │     approvals)        │  │                                 │   │
│  └──────────┘  └──────────────────────┘  └──────────────────────────────────┘   │
└──────────────────────────────┬──────────────────────────────────────────────────┘
                               │ WebSocket
                               ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│                         ORCHESTRATOR (FastAPI on host)                           │
│                                                                                  │
│  ┌────────────┐  ┌───────────┐  ┌───────────┐  ┌────────────┐  ┌────────────┐  │
│  │ Routes +   │  │ IPC       │  │ Scheduler │  │ MCP        │  │ SQLite DB  │  │
│  │ WebSocket  │  │ Polling   │  │ (10s tick)│  │ Manager    │  │ (source of │  │
│  │            │  │ (0.5s)    │  │           │  │ (host-side)│  │  truth)    │  │
│  └────────────┘  └─────┬─────┘  └───────────┘  └────────────┘  └────────────┘  │
│                         │                                                        │
│          ┌──────────────┼──────────────────────────────────┐                     │
│          │   File-based IPC (atomic writes)                │                     │
│          │   input.json / output.json (messages)           │                     │
│          │   request.json / response.json (tool calls)     │                     │
│          └──────────────┼──────────────────────────────────┘                     │
└─────────────────────────┼────────────────────────────────────────────────────────┘
                          │ Podman bind-mount
            ┌─────────────┼────────────────────────────────────┐
            │             ▼                                     │
            │  ┌─────────────────────────────────────────────┐  │
            │  │ WORKER CONTAINER (per agent, 2GB/2CPU)      │  │
            │  │                                              │  │
            │  │  worker.py → agent.py → Claude Agent SDK    │  │
            │  │       │          │                            │  │
            │  │  memory.py   search.py ←→ Ollama (embed)    │  │
            │  │       │          │                            │  │
            │  │  Tools: memory, schedule, slack_thread,      │  │
            │  │         mcp_proxy (→ GitHub, Slack, Jira)    │  │
            │  └─────────────────────────────────────────────┘  │
            │  data/agents/<agent-name>/  (persistent workspace)│
            └───────────────────────────────────────────────────┘
```

## How a Message Flows End-to-End

```
 You type "Check my open PRs" and press Enter
                    │
                    ▼
 ① Browser sends WebSocket frame → Orchestrator
                    │
                    ▼
 ② Orchestrator stores in SQLite (messages + message_queue)
                    │
                    ▼
 ③ Polling loop (0.5s) writes input.json to agent's workspace
                    │
                    ▼
 ④ Worker detects input.json, reads it, deletes it (ACK)
                    │
                    ▼
 ⑤ Worker runs hybrid search on "open PRs" → retrieves relevant memories
                    │
                    ▼
 ⑥ Worker assembles system prompt (identity + memory + facts + search results)
                    │
                    ▼
 ⑦ Claude Agent SDK processes query, decides to call mcp__github__gh tool
                    │
                    ▼
 ⑧ Worker writes request.json → Orchestrator runs "gh pr list" → response.json
                    │
                    ▼
 ⑨ SDK gets tool result, generates response text (streamed as token events)
                    │
                    ▼
 ⑩ Worker buffers events → flushes to output.json (atomic write)
                    │
                    ▼
 ⑪ Orchestrator reads output.json → forwards to WebSocket → Browser renders
```

## The Memory & Learning System

Your agents learn and remember across sessions. This is the most important system to understand for productivity.

```
  ┌──────────────────────────────────────────────────────────────┐
  │                    CONVERSATION                              │
  │  User: "My timezone is IST, I use vim, project is on Quay"  │
  └───────────────────────────┬──────────────────────────────────┘
                              │
           ┌──────────────────┼──────────────────────────┐
           ▼                  ▼                          ▼
    ┌──────────────┐  ┌──────────────────┐  ┌────────────────────┐
    │ Agent uses   │  │ On session end   │  │ Agent explicitly   │
    │ memory_store │  │ or context       │  │ writes to          │
    │ tool         │  │ overflow:        │  │ MEMORY.md          │
    │              │  │ auto-summarize   │  │ (learned patterns) │
    └──────┬───────┘  └────────┬─────────┘  └────────────────────┘
           │                   │
           ▼                   ▼
    ┌──────────────┐  ┌──────────────────────────────────┐
    │ facts table  │  │ memory/2026-04-30.md             │
    │ (structured) │  │ (daily narrative summaries)       │
    │              │  │                                    │
    │ key: tz      │  │ Indexed for hybrid search:        │
    │ val: IST     │  │  - BM25 (keyword match)           │
    │ cat: pref    │  │  - Vector (semantic similarity)   │
    └──────┬───────┘  └───────────────┬──────────────────┘
           │                          │
           └──────────┬───────────────┘
                      ▼
    ┌──────────────────────────────────────────────────────┐
    │         NEXT CONVERSATION                            │
    │                                                      │
    │  System prompt includes:                             │
    │  ├─ Identity (CLAUDE.md + SOUL.md)                   │
    │  ├─ Continuation summary (if session split)          │
    │  ├─ Active plan (if multi-step task in progress)     │
    │  ├─ Known Facts (timezone=IST, editor=vim, etc.)     │
    │  ├─ MEMORY.md (learned patterns, user preferences)   │
    │  └─ Retrieved Context (relevant past conversations)  │
    └──────────────────────────────────────────────────────┘
```

### How memory is assembled into each prompt

On each message, the worker constructs the system prompt from up to six sections. Each section has a priority and a token budget. Sections are filled in priority order (1 = highest); when the total budget (~25,000 tokens) is exhausted, lower-priority sections are truncated or omitted entirely.

| Priority | Section | Budget | Source |
|----------|---------|--------|--------|
| 1 | Identity | 3,000 tokens | CLAUDE.md + SOUL.md |
| 2 | Continuation summary | 5,000 tokens | Previous session summary (after context split) |
| 3 | Active plan | 10,000 tokens | First .md file in /workspace/.plans/ |
| 4 | Known facts | 2,000 tokens | Structured key-value pairs from facts table |
| 5 | Persistent memory | 1,000 tokens | MEMORY.md |
| 6 | Retrieved context | 4,000 tokens | Top 10 hybrid search results (BM25 + vector, merged via RRF) |

### Hybrid search

Each incoming message triggers a search against the worker's SQLite database:

1. **Query rewriting** — strip greetings, hedging, stop words; preserve technical terms
2. **BM25 keyword search** via FTS5 (top 20 by rank)
3. **Semantic vector search** via sqlite-vec with Ollama embeddings (top 20 by distance)
4. **Reciprocal Rank Fusion** (k=60) merges both result sets
5. Results below minimum RRF score (0.015) are discarded
6. Top 10 merged results are injected as retrieved context

### Fact extraction & supersession

When a session is summarized (on split, clear context, or shutdown), Claude extracts structured facts. Each fact has a key, value, and category (preference, project, decision, entity, config, general).

Facts use supersession tracking: when a value changes, the old row is marked superseded and a new row inserted. The old value is preserved, not overwritten. This creates the agent's learning loop: sessions produce summaries, summaries produce facts, facts inform future sessions.

## Context Overflow — Invisible Session Splits

```
  Message 1 ───► Message 2 ───► ... ───► Message N
                                              │
                               Input tokens > 80% of 200K
                                              │
                                              ▼
                                    ┌──────────────────┐
                                    │ AUTOMATIC SPLIT   │
                                    │                    │
                                    │ 1. Summarize       │
                                    │ 2. Extract facts   │
                                    │ 3. Write memory    │
                                    │ 4. Keep last 20    │
                                    │    messages         │
                                    │ 5. New SDK session  │
                                    └──────────────────┘
                                              │
                                              ▼
                                    You see NO interruption.
                                    Agent continues with
                                    summary + facts as context.
```

The system has two session layers:

- **SDK session** — managed by Claude Agent SDK. Resets on context overflow. JSONL files in /workspace/sessions/.
- **Orchestrator session** — represents the WebSocket connection. Never resets on overflow.

On overflow, only the SDK session resets. The continuation summary is injected into the new session's system prompt so the agent retains context. The WebSocket connection is completely unaffected — the split is invisible to you.

## Scheduled Tasks & Triggers

Agents can create recurring tasks that run autonomously in ephemeral containers.

```
  ┌────────────────────────────────────────────────────────┐
  │                   TRIGGER TYPES                        │
  │                                                        │
  │  interval ─────► "Every 30 min, check CI status"       │
  │                                                        │
  │  file_watch ───► "When new files appear in /reports"   │
  │                                                        │
  │  webhook ──────► "When GitHub Actions POSTs to me"     │
  │                                                        │
  │  github_pr ────► "When new comments on PR #42"         │
  │                                                        │
  │  github_issues ► "When new issues labeled 'urgent'"    │
  │                                                        │
  │  slack_channel ► "When messages appear in #incidents"  │
  └────────────────────────────────────────────────────────┘
                          │
                          ▼
              Scheduler spawns ephemeral container
              Agent runs with full capabilities
              Results stored, visible in UI
```

The scheduler runs on a 10-second tick. Interval tasks support idle backoff — the interval doubles when no activity is found, and resets when the agent calls `signal_activity`. Webhook tasks accept HTTP POST with Bearer token auth; the payload (up to 5,000 chars) is appended to the task prompt.

## Tool & Integration Security Model

```
  ┌──────────────────────────────────────────┐
  │  WORKER CONTAINER (untrusted sandbox)     │
  │                                           │
  │  Can: read/write /workspace, run bash,    │
  │       search web, fetch URLs              │
  │                                           │
  │  Cannot: see credentials, access other    │
  │          agents, reach host services      │
  │                                           │
  │  To use GitHub/Slack/Jira:                │
  │    writes request.json ──────────────┐    │
  │    waits for response.json ◄─────┐   │    │
  └──────────────────────────────────┼───┼────┘
                                     │   │
  ┌──────────────────────────────────┼───┼────┐
  │  ORCHESTRATOR (trusted host)     │   │    │
  │                                  │   ▼    │
  │  Reads request, checks permission│        │
  │                                  │        │
  │  Auto-approved: read-only ops ───┼────►   │
  │  Needs approval: create/merge ───┼──► UI  │
  │  Denied: delete repos, auth ─────┼──► ✗   │
  │                                  │        │
  │  Credentials NEVER leave host    │        │
  └───────────────────────────────────────────┘
```

### Available integrations

| Integration | Transport | Tools | Credentials |
|-------------|-----------|-------|-------------|
| GitHub | Builtin MCP (stdio) | `gh` CLI commands, `git_push` | `gh auth login` on host |
| Slack | Builtin MCP (stdio) | find_channel, read_channel, read_dm, search_messages, send_note_to_self | SLACK_XOXC_TOKEN, SLACK_D_COOKIE, MY_MEMBER_ID |
| Jira | Custom MCP (stdio) | via mcp-atlassian (`uvx mcp-atlassian`) | Atlassian API token |
| Google Workspace | Builtin MCP (stdio) | `gws` CLI (Drive, Sheets, Calendar, Docs, Gmail, etc.) | `gws auth login` on host |
| Custom | Any MCP server | Configured via UI | Stored on host |

### Permission tiers (GitHub example)

- **Auto-approved**: pr/issue list/view/diff, repo list, search, workflow view
- **Requires UI approval**: pr/issue create/merge/close/comment, release create, workflow run
- **Denied**: auth, config, secret, repo delete/archive, ssh-key

## Agent Identity Files

Each agent has four identity files in its workspace, seeded from templates on creation:

| File | Purpose | Editable via UI |
|------|---------|-----------------|
| CLAUDE.md | Behavioral instructions, task planning rules, memory/skill usage | Yes |
| SOUL.md | Personality and communication style | Yes |
| MEMORY.md | Persistent identity context (who the agent is, user preferences) | Yes |
| BOOTSTRAP.md | First-conversation script (runs once on agent creation) | No (consumed on first run) |

## Available Worker Tools

| Tool | Namespace | Purpose |
|------|-----------|---------|
| memory_search | mcp__memory__ | Search past conversations and facts |
| memory_store | mcp__memory__ | Store a persistent fact (key/value/category) |
| memory_delete | mcp__memory__ | Remove an outdated fact |
| create_schedule | mcp__schedule__ | Create a recurring scheduled task |
| list/get/update/delete_schedule | mcp__schedule__ | Manage scheduled tasks |
| pause/resume_schedule | mcp__schedule__ | Pause/resume execution |
| signal_activity | mcp__schedule__ | Reset idle backoff when activity detected |
| register_slack_thread | mcp__slack_thread__ | Monitor a Slack thread for new replies |
| Read, Write, Edit, Bash, Glob, Grep | builtin | File and shell operations in /workspace |
| WebSearch, WebFetch | builtin | Web search and URL fetching |

Plus any MCP proxy tools from enabled integrations (e.g., `mcp__github__gh`, `mcp__slack__read_channel`).

## Skills System

Skills are markdown instruction files that guide agent behavior. They are not executable tools — they provide knowledge and procedures.

- **Builtin skills**: `schedule`, `slack`, `jira` — shipped with the platform in `skills/`
- **Agent-created skills**: drafted to `/workspace/skill-drafts/`, approved via UI, installed to `/workspace/.claude/skills/`
- **Always-enabled skills**: marked in YAML frontmatter, cannot be removed

When an agent figures out a complex workflow after trial and error, it offers to save it as a reusable skill for next time.

## Boot Recovery

On orchestrator restart, state is reconciled before accepting connections:

1. Force-remove all managed containers (fresh start)
2. Re-queue IN-FLIGHT messages as QUEUED
3. Delete stale IPC files from all agent workspaces
4. Finalize messages stuck in 'streaming' status
5. Reset container statuses to 'stopped'
6. Mark pending/running scheduled tasks as 'failed'
7. Seed always-enabled builtin skills for all agents

Workers deduplicate by message_id to handle at-least-once delivery after recovery.

## Container Crash Recovery

1. Orchestrator detects worker process exit
2. Error forwarded to WebSocket, container status set to 'error'
3. Container cleaned up via `podman rm -f`
4. If WebSocket still connected, container is respawned
5. Circuit breaker: 3+ crashes in 10 minutes marks the agent as unavailable

## How to Use Takopod Effectively

### 1. Create specialized agents for different roles

Don't use one agent for everything. Create agents with distinct purposes:

- **"ops"** — monitors CI, PRs, Jira tickets. Set up scheduled tasks.
- **"dev"** — helps with code, reviews PRs, runs tests. Give it GitHub MCP.
- **"research"** — searches the web, reads docs, summarizes findings.

Each agent maintains its own memory, personality, and workspace.

### 2. Invest in the first conversation

When you create a new agent, it runs a bootstrap — it asks your name, role, and what you need help with. Take this seriously. The more context you give upfront, the better every future interaction will be.

### 3. Use the memory tools explicitly

Tell your agent things it should remember:

- "Remember that I prefer concise PR descriptions"
- "Remember that our staging cluster is on GKE project X"
- "Remember that PROJQUAY is our Jira project"

These are stored as structured facts and injected into every future prompt.

### 4. Set up scheduled tasks for monitoring

Ask your agent:

- "Monitor PR #42 for new comments and summarize them for me"
- "Check the #incidents Slack channel every 15 minutes and alert me to anything P1"
- "Every morning at 9am, give me a summary of open Jira issues in PROJQUAY"

The agent creates these as scheduled tasks that run autonomously in ephemeral containers.

### 5. Customize identity files

Through the agent settings UI, edit:

- **CLAUDE.md** — add project-specific rules, coding standards, repo conventions
- **SOUL.md** — adjust communication style ("be very brief", "use bullet points")
- **MEMORY.md** — add persistent context the agent should always know

### 6. Enable relevant integrations

From the MCP panel in the right sidebar:

- Enable **GitHub** for PR/issue management
- Enable **Slack** for message reading/searching
- Enable **Jira** (add as custom MCP server) for issue tracking
- Enable **Google Workspace** for Drive, Calendar, Gmail, etc.

### 7. Let agents draft skills

When an agent figures out a complex workflow (e.g., "how to deploy to staging"), it offers to save it as a skill. Approve it — next time you or the agent can invoke that skill instead of figuring it out again.

### 8. Use plans for complex tasks

For multi-step work, the agent creates a plan file at `/workspace/.plans/`. It works through the checklist across messages and even across session splits. You can view and edit these from the file browser panel.

### 9. Clear context when switching topics

Hit "Clear Context" when you're done with a topic. This triggers a summary + memory save, then starts fresh. The agent retains all facts and memories but gets a clean conversation window.

## Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| GOOGLE_CLOUD_PROJECT | — | GCP project ID for Vertex AI |
| GOOGLE_CLOUD_REGION | — | GCP region for Vertex AI |
| OLLAMA_ENABLED | true | Enable/disable Ollama embeddings |
| OLLAMA_HOST_URL | http://localhost:11434 | Ollama endpoint for orchestrator |
| SHUTDOWN_TIMEOUT_SECONDS | 30 | Graceful shutdown timeout |
| IDLE_TIMEOUT_SECONDS | 300 | Container idle reaper timeout |
| SLACK_XOXC_TOKEN | — | Slack user token (optional) |
| SLACK_D_COOKIE | — | Slack auth cookie (optional) |
| MY_MEMBER_ID | — | Your Slack user ID (optional) |

## Key File Paths

| Path | Purpose |
|------|---------|
| orchestrator/main.py | App lifespan, startup, shutdown |
| orchestrator/routes.py | All API endpoints + WebSocket handler |
| orchestrator/ipc.py | File-based IPC polling loop |
| orchestrator/container_manager.py | Podman container lifecycle |
| orchestrator/scheduler.py | Scheduled tasks + idle reaper |
| orchestrator/mcp_manager.py | MCP server process management |
| worker/worker.py | Main worker polling loop |
| worker/agent.py | Claude Agent SDK integration + system prompt assembly |
| worker/memory.py | Summarization, fact extraction, memory files |
| worker/search.py | Hybrid search (BM25 + vector + RRF) |
| worker/tools/ | Memory, schedule, slack_thread, MCP proxy tools |
| data/agents/<name>/ | Per-agent persistent workspace |
| data/takopod.db | Orchestrator SQLite database |
| agent_templates/default/ | Default CLAUDE.md, SOUL.md, MEMORY.md, BOOTSTRAP.md |
| skills/ | Builtin skills (schedule, slack, jira) |
| integrations/ | Builtin MCP servers (GitHub, Slack, Jira, GWS) |
