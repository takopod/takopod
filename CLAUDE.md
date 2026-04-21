# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**takopod** is a multi-agent AI platform where each agent runs in an isolated Podman container with persistent memory, file workspace, and real-time streaming chat. See `ARCHITECTURE.md` for how the system works.

## Tech Stack

- **Backend**: Python 3.12+, FastAPI, aiosqlite (async SQLite)
- **Frontend**: React 19, TypeScript, Vite, Tailwind CSS 4, shadcn/ui
- **Containerization**: Podman (rootless containers)
- **Agent Runtime**: Claude Agent SDK (`claude-agent-sdk`, Vertex AI backend)
- **Embedding/Search**: Ollama with nomic-embed-text (hybrid BM25 + vector via sqlite-vec)
- **IPC**: File-based with atomic writes (input.json/output.json for messages, request.json/response.json for tool calls)
- **Integrations**: Slack SDK, GitHub REST API, MCP servers

## Build & Development Commands

```bash
# Full setup (Python deps via uv, Node deps, build worker image, build web UI)
make

# Individual targets
make install          # uv sync + npm install
make build-worker     # Build Podman worker image from worker/Containerfile
make web-ui           # cd web && npm run build
make dev              # Builds worker image, then runs uvicorn on localhost:8000

# Ollama embedding service (must be running before orchestrator)
make setup-ollama     # One-time: pull image + nomic-embed-text model
make start-ollama     # Start Ollama container on takopod-internal network
make stop-ollama      # Stop + remove Ollama container

# Production mode
source .venv/bin/activate
takopod start [--host 127.0.0.1] [--port 9000]
takopod stop
```

### Frontend development

```bash
cd web
npm run dev           # Vite dev server (HMR)
npm run build         # TypeScript check + Vite production build
npm run lint          # ESLint
npm run typecheck     # tsc --noEmit
npm run format        # Prettier (ts, tsx files)
```

## Key Concepts

- **Agent-centric routing**: All state is keyed by `agent_id`. No sessions table.
- **Worker output**: Workers do NOT use stdout (it's DEVNULL). Events go through `emit()` -> in-memory buffer -> `output.json` file (atomic write).
- **Atomic writes**: All IPC files use temp file + `os.fsync()` + `os.rename()`. Never bypass this.
- **Context assembly**: System prompt is built from CLAUDE.md + SOUL.md + agents list + memory + hybrid search results + continuation summary (see `worker/agent.py`).

## Common Development Tasks

### Adding a New API Endpoint

1. Define Pydantic model in `orchestrator/models.py`
2. Implement handler in `orchestrator/routes.py` or a sub-router (`slack_routes.py`, `github_routes.py`, `oauth_routes.py`, `search_routes.py`)
3. Add WebSocket frame type to `models.py` if streaming is needed
4. Implement client via `fetch()` in the relevant component (no centralized API client)

### Adding a New Tool to the Worker

1. Add tool in `worker/tools/`
2. Tool output goes through `emit()` -> in-memory buffer -> `output.json`

### Adding/Editing Agent Templates

Edit files in `agent_templates/<type>/` (CLAUDE.md, SOUL.md, MEMORY.md). New agents use the template; existing agents keep their own copies.

### Adding MCP Server Integration

Builtin MCP servers live in `integrations/` and are managed by `orchestrator/mcp_manager.py`. Custom servers are configured via UI and stored in the `mcp_servers` + `agent_mcp_servers` tables. Workers call MCP tools via `worker/tools/mcp_proxy.py`.

## Key Entry Points

- **Orchestrator**: `orchestrator/main.py` (lifespan) -> `orchestrator/routes.py` (WebSocket + HTTP)
- **IPC + polling**: `orchestrator/ipc.py` (atomic writes, message queue, output.json reading)
- **Containers**: `orchestrator/container_manager.py` (Podman spawn/kill)
- **Worker**: `worker/worker.py` (polling, emit, flush) -> `worker/agent.py` (SDK integration, system prompt)
- **Memory/search**: `worker/memory.py` + `worker/search.py`
- **Boot recovery**: `orchestrator/boot_recovery.py`
- **Scheduler**: `orchestrator/scheduler.py` (agentic tasks + scheduled tasks + reaper)
- **UI**: `web/src/App.tsx` + `web/src/hooks/use-websocket.ts`

## Code Conventions

- **Python**: Type hints (PEP 484), async/await for all I/O, `_private` functions, `CONSTANT` globals
- **SQL**: Numbered migration files in `*/migrations/`, idempotent where possible, WAL mode enabled
- **React/TypeScript**: Hooks-based, shadcn/ui components, Tailwind utility classes, kebab-case filenames
