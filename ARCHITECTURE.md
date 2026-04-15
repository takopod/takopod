# rhclaw — Architecture

## 1. System Architecture

### Components

The platform has four components:

- **Orchestrator** (FastAPI, single process on host) — the central coordinator. Manages all state in SQLite, spawns and monitors Podman worker containers, exposes HTTP API and WebSocket for the UI, and runs polling loops for file-based IPC with each active agent.
- **Worker Container** (one per active agent) — an isolated Podman container running a Python process that uses the Claude Agent SDK. Polls for input messages, calls the SDK, and writes response events back via file IPC.
- **Workspace Directory** (one per agent, persistent on host) — bind-mounted into the worker container at `/workspace`. Holds identity files, IPC files, session history, daily memory files, and a per-agent SQLite database. Survives container restarts.
- **Ollama Container** (singleton, shared) — runs the `nomic-embed-text` embedding model. Workers call it over HTTP on a shared Podman network for embedding generation and search.

### Data Flow

1. User sends a message via WebSocket to the orchestrator.
2. Orchestrator stores the message in SQLite (`messages` table) and enqueues it (`message_queue` with status `QUEUED`).
3. Orchestrator's polling loop (0.5s tick per active agent) batches all `QUEUED` messages into `input.json` via atomic write, marks them `IN-FLIGHT`.
4. Worker's polling loop detects `input.json`, reads it, deletes it (ACK).
5. Orchestrator's next tick detects the deletion, marks messages `PROCESSED`, flushes any new `QUEUED` messages.
6. Worker invokes the Claude Agent SDK with the message plus retrieved context.
7. Worker inserts response events into the `worker_responses` table, then flushes them to `output.json` via atomic write.
8. Orchestrator's polling loop detects `output.json`, reads it, deletes it, and forwards events to the WebSocket.
9. UI renders streaming tokens, tool calls, and completion.

### Data Model

The system is **agent-centric**. All routing uses `agent_id` directly — there is no sessions table or session-level indirection. The orchestrator SQLite database is the single source of truth for agents, messages, message queue, container state, scheduled tasks, MCP server config, and integration state. Each worker has its own SQLite database in its workspace for deduplication, memory indexing, FTS5, and vector search.

The `messages` table stores conversation history (the permanent record). The `message_queue` table is a separate delivery queue — it tracks the IPC lifecycle of getting a message (or system command) from the orchestrator into the worker's `input.json`. User messages exist in both tables; system commands (clear_context, shutdown) exist only in the queue since they aren't conversation history. The queue should be periodically cleaned up: `PROCESSED` rows have served their purpose and can be deleted after a retention period.

Schema is managed via numbered SQL migration files applied sequentially on boot. No external migration tooling (no Alembic).

### Two IPC Channels

All IPC is file-based, using atomic writes (temp file + `os.fsync()` + `os.rename()`) and poll-based consumption. Each agent has its own set of IPC files in its workspace directory.

**Message channel** (0.5s poll) — carries user conversations:
- `input.json`: Orchestrator writes batched messages, worker reads and deletes (ACK).
- `output.json`: Worker writes response events, orchestrator reads and deletes.

**Tool channel** (0.5s poll) — carries worker requests to the orchestrator (e.g., schedule CRUD, MCP tool calls):
- `request.json`: Worker writes a request, orchestrator reads and deletes.
- `response.json`: Orchestrator writes the result, worker reads and deletes.

### Worker Output Mechanism

Workers do NOT stream to stdout — stdout and stderr are `DEVNULL`. Instead, the worker's `emit()` function inserts events into a `worker_responses` table in the per-agent SQLite database with status `pending`. A separate `flush_responses()` call batches all pending rows into `output.json` via atomic write and marks them `sent`. This decouples event production from file I/O and provides crash safety.

## 2. Atomic Write Protocol

All writes to IPC files must follow this protocol to prevent data corruption:

1. Write to a temp file **in the same directory** as the target (same filesystem required for atomic rename).
2. `os.fsync(fd)` on the file descriptor before closing — prevents kernel reordering of write and rename.
3. `os.rename()` to the final path — atomic on POSIX when source and destination are on the same mount.
4. `try...finally` cleanup — remove the temp file on any failure.

This protocol is critical for data integrity and must never be bypassed for any IPC file.

## 3. Container Model

### Lifecycle

- **Spawn**: Orchestrator spawns a Podman container via `asyncio.create_subprocess_exec`, bind-mounting the agent's workspace directory to `/workspace`. The container runs a long-lived polling loop.
- **Active**: Both sides poll at 0.5s. Worker processes messages from `input.json`, writes events to `output.json`.
- **Idle**: Container stays alive (avoids cold-start latency). After `IDLE_TIMEOUT_SECONDS` (default: 300s, configurable via env var), the periodic reaper closes the WebSocket and stops the container.
- **End**: Orchestrator issues `podman stop`, then `podman kill` if unresponsive, then `podman rm -f`. The `--rm` flag is intentionally not used so containers can be discovered during boot recovery. The workspace directory is never deleted.

### Resource Constraints

- `--network rhclaw-internal` — shared Podman network for outbound internet access and Ollama DNS resolution (`ollama:11434`). Does not expose host-local services.
- `--memory 2g`, `--cpus 2`, `--pids-limit 256`
- `--tmpfs /tmp:rw,size=512m`, `--tmpfs /var/tmp:rw,size=64m`
- `-v <host_dir>:/workspace:Z` — agent workspace bind mount
- `-v ~/.config/gcloud:/root/.config/gcloud:ro,Z` — Vertex AI credentials (read-only)
- Labels: `rhclaw.managed=true`, `rhclaw.agent_id=<id>` — used for boot recovery container discovery

### Security & Blast Radius Isolation

Worker agents can fetch arbitrary external URLs via the Claude Agent SDK's `WebSearch` and `WebFetch` tools, exposing them to prompt injection from malicious web content. The mitigation strategy is **blast radius isolation**:

- **Filesystem isolation**: The only writable paths are `/workspace` (scoped to one agent) and ephemeral tmpfs mounts. A compromised worker cannot access other agents' workspaces or the host filesystem.
- **Process isolation**: `--pids-limit 256` prevents fork bombs. Rootless containers with no elevated capabilities.
- **Memory/CPU isolation**: Prevents resource exhaustion from affecting the host or other containers.
- **Network isolation**: No exposed ports on worker containers. The only communication back to the orchestrator is through IPC files in the workspace bind mount. The only reachable container is the stateless Ollama embedding service.
- **Session ephemerality**: Containers are destroyed on session end. The workspace persists for memory continuity but contains only that agent's data.
- **Orchestrator as trust boundary**: The orchestrator validates all events from workers. A compromised worker cannot inject messages into another agent's `input.json`.

**Privileged tool brokering**: Tools that access internal systems (databases, credentials, internal APIs) must not run inside the worker container. They should be brokered through MCP servers that enforce their own authorization and audit logging.

### Embedding Service (Ollama)

The Ollama container is a long-lived singleton on the `rhclaw-internal` network. Workers call `POST http://ollama:11434/api/embed` for embedding generation. It uses a named Podman volume (`ollama-models`) for persistent model storage. It has no access to any agent's workspace — it receives text and returns vectors.

Ollama must be started manually (`make start-ollama`) before the orchestrator. The orchestrator checks Ollama health but does not auto-start it.

## 4. Memory System

### Identity Files

Each agent has three identity files in its workspace, seeded from templates on agent creation:

- `CLAUDE.md` — behavioral instructions and rules
- `SOUL.md` — personality and communication style
- `MEMORY.md` — persistent identity context (who the agent is, user preferences)

These are read-only from the worker's perspective. The user can edit them via the UI; changes take effect at the next context assembly.

### Context Assembly

On each message, the worker constructs the system prompt in this order:

1. `CLAUDE.md` + `SOUL.md`
2. Available agents list (from `agents.json`, written by orchestrator)
3. Memory context: `MEMORY.md` (always in full) + recent daily memory files (up to 4000 token budget, most recent first)
4. Retrieved context: hybrid search results (top 10 via Reciprocal Rank Fusion)
5. Continuation summary (if resuming after a session split)

### Hybrid Search

Each incoming message triggers a hybrid search against the worker's SQLite database:

- **BM25 keyword search** via FTS5 (top 20 by rank)
- **Semantic vector search** via sqlite-vec with Ollama embeddings (top 20 by distance)
- **Reciprocal Rank Fusion** (k=60) merges both result sets, deduplicated by content hash
- Top 10 merged results are injected as retrieved context

### Session Split (Context Overflow)

When input tokens exceed 80% of the 200K context window:

1. Worker summarizes the current session via a Claude API call.
2. Summary is appended to a daily memory file (`memory/YYYY-MM-DD.md`).
3. If the daily file exceeds a size threshold, continuation files are created (`-2.md`, `-3.md`, etc.).
4. **Compaction**: When a 4th continuation file would be created, all files for that day are distilled into a single summary file via a Claude API call.
5. Worker starts a new SDK session with the summary as continuation context.
6. The split is invisible to the user — the WebSocket connection remains unchanged.

### Session End

On session end (UI disconnect or "Clear Context"), the worker summarizes the session, appends it to daily memory, and emits a `done` status event.

## 5. Backpressure & Rate Limiting

- **Rate limit**: Max 10 messages per 60-second sliding window per agent. Tracked in-memory. Exceeding returns `{"type": "error", "code": "RATE_LIMITED"}`.
- **Queue depth cap**: Max 50 `QUEUED` messages per agent. Exceeding returns `{"type": "error", "code": "QUEUE_FULL"}`.
- Both thresholds are configurable constants. In-memory state resets on orchestrator restart.

## 6. Boot Recovery

On startup, before accepting connections, the orchestrator reconciles state. Order matters — containers must be killed before files are touched.

1. Discover all containers with label `rhclaw.managed=true`.
2. Force-remove all discovered containers.
3. Re-queue `IN-FLIGHT` messages as `QUEUED`.
4. Delete stale IPC files (`input.json`, `output.json`, `request.json`, `response.json`) from all agent workspaces.
5. Reset all active container records to `stopped`.
6. Mark pending/running scheduled tasks as `failed`.
7. Ensure the `rhclaw-internal` Podman network exists.

Workers deduplicate by `message_id` (via `processed_messages` table) to handle at-least-once delivery after recovery.

### Container Crash Recovery

1. Orchestrator detects worker process exit and generates a `system_error` event.
2. Error forwarded to WebSocket, container status set to `error`.
3. Container cleaned up via `podman rm -f`.
4. If WebSocket is still connected, container is respawned. If disconnected, crash is logged.
5. Circuit breaker: 3+ crashes in 10 minutes marks the agent as unavailable.

## 7. Scheduled Tasks & Periodic Reaper

The orchestrator runs a background scheduler loop (10-second tick):

- **Agentic tasks**: User-created recurring prompts with configurable intervals and allowed tools. Executed by spawning ephemeral worker containers.
- **Scheduled tasks**: System-level tasks (e.g., memory compaction). Has retry logic and configurable timeouts (default: 15 minutes).
- **Periodic reaper** (every 30 seconds): Enforces scheduled task timeouts (kills container, retries or fails) and session idle TTL (default: 300 seconds, closes WebSocket and stops container).

## 8. IPC Event Types

Events written by the worker to `output.json`:

- `token` — streaming LLM output (content, seq number)
- `status` — lifecycle signals (thinking, done, error, context_cleared)
- `tool_call` / `tool_result` — tool execution
- `complete` — full assembled response with token usage
- `task_result` — result from scheduled task execution
- `system_error` — error with optional fatal flag
- `schedule_compaction` — signals orchestrator to schedule memory compaction

## 9. Key Design Decisions

1. **File-based IPC over stdin/sockets**: Atomic rename is simple, debuggable (`cat input.json`), and avoids stdin framing/deadlock issues. The SQLite message queue handles backpressure. No network ports exposed on containers.
2. **SQLite over PostgreSQL**: Single-node deployment. WAL mode handles concurrency. No ops overhead.
3. **Hybrid search over pure vector**: BM25 catches exact keyword matches (error codes, function names) that embeddings miss. RRF fusion gets the best of both without weight tuning.
4. **Containers stay alive during session**: Avoids 2-5 second cold-start latency per message at the cost of ~50MB memory per container.
5. **Agent-centric routing**: All state keyed by `agent_id` directly — no session indirection layer. Simpler model for single-user deployment.

## 10. Not Yet Implemented

- **Inter-agent delegation**: Workers emitting `delegate` events, orchestrator routing to ephemeral delegation containers, `active_delegations` tracking with 5-minute timeout.
- **Admin API**: `/admin/sessions/*` endpoints for force-killing sessions and listing active state.
- **`--read-only` container flag**: Documented as a security goal but not yet applied.
