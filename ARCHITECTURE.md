# rhclaw — Multi-Agent AI Platform Architecture

## 1. System Architecture

### Data Flow

The system follows a unidirectional data flow with two distinct IPC channels:

1. **User -> UI**: User types a message in the stateless frontend.
2. **UI -> Orchestrator**: Message sent over a persistent WebSocket connection to FastAPI.
3. **Orchestrator -> SQLite**: Message stored in the orchestrator's database (source of truth for all conversations).
4. **Orchestrator -> SQLite Queue**: Message stored in `message_queue` with status `QUEUED`.
5. **Orchestrator -> File System**: Orchestrator runs a 0.5s polling loop per active session. Each tick: if `IN-FLIGHT` messages exist and `input.json` is gone, mark them `PROCESSED` (worker has ACK'd). Then, if `QUEUED` messages exist and no `input.json` exists, batch all `QUEUED` messages into `input.json` (ordered by timestamp) via atomic write (see Atomic Write Protocol below), mark them `IN-FLIGHT`.
6. **File System -> Worker**: Worker's 0.5s polling loop detects `input.json`, reads it, deletes it (ACK). The orchestrator's next polling tick detects the deletion and marks `IN-FLIGHT` messages as `PROCESSED`, then flushes any new `QUEUED` messages.
7. **Worker -> Claude Agent SDK**: Worker invokes the Claude Agent SDK with the message + retrieved context from `worker_db.sqlite`.
8. **Worker -> stdout (JSONL)**: Worker streams structured JSON Lines to stdout as tokens arrive.
9. **stdout -> Orchestrator**: Orchestrator reads the container's stdout line-by-line via `asyncio.subprocess.PIPE`, parses each JSON line.
10. **Orchestrator -> UI**: Orchestrator forwards parsed token/status/tool events through the WebSocket to the frontend.

### WebSocket Backpressure

The orchestrator enforces two per-session limits before inserting into `message_queue`:

- **Rate limit**: Max 10 messages per 60-second sliding window. Tracked in-memory with a per-session deque of timestamps. Exceeding the limit returns a WebSocket error frame `{"type": "error", "code": "RATE_LIMITED", "retry_after_seconds": N}` without queuing. The in-memory deques reset on orchestrator restart — this is acceptable since it's a brief window of leniency, not a security bypass.
- **Queue depth cap**: Max 50 `QUEUED` messages per session. If the worker is backed up, new messages are rejected with `{"type": "error", "code": "QUEUE_FULL"}`. This prevents unbounded SQLite growth from a misbehaving or compromised client.

Both thresholds are configurable constants.

### Admin API

HTTP endpoints for manual intervention. All admin endpoints are prefixed with `/admin` and must be authenticated (mechanism TBD — API key, internal network restriction, or both).

**`POST /admin/sessions/{session_id}/kill`** — Force-kill a session's worker container.

1. Looks up the active container in `agent_containers` by `session_id`.
2. Returns `404` if no active container exists for the session.
3. Runs `podman kill <container_id>`, then `podman rm -f <container_id>`.
4. Sets `agent_containers.status = 'stopped'` and `agent_containers.stopped_at = now`.
5. Marks any `IN-FLIGHT` messages for the session as `QUEUED` in `message_queue` (same as boot recovery — allows reprocessing if the session is resumed).
6. If a WebSocket is connected for the session, sends `{"type": "system_error", "error": "Session terminated by admin", "fatal": true}` and closes the connection.
7. Returns `200` with `{"killed": true, "container_id": "..."}`.

**`GET /admin/sessions`** — List active sessions with container status.

Returns an array of active sessions with: `session_id`, `agent_type`, `container_status`, `last_activity`, `queued_message_count`, `in_flight_message_count`.

**`GET /admin/sessions/{session_id}`** — Get detailed session state.

Returns: session metadata, container status, `message_queue` breakdown by status, active delegations, crash count.

### Agent Files API

HTTP endpoints for browsing and editing files in an agent's workspace directory. Prefixed with `/api/agents/{agent_id}/files`. The orchestrator resolves paths relative to the agent's `host_dir` from the `agents` table.

**Security**: All endpoints must validate that the resolved absolute path stays within the agent's `host_dir` (path traversal protection via `Path.resolve()` + prefix check). Requests that escape the workspace return `403`.

**`GET /api/agents/{agent_id}/files`** — List files in the workspace (or a subdirectory via `?path=memory/`).

Returns a flat array of entries: `name`, `path` (relative to workspace root), `type` (`file` | `directory`), `size`, `modified_at`. Does not recurse into subdirectories unless `?recursive=true` is specified.

**`GET /api/agents/{agent_id}/files/{path:path}`** — Read a file's content.

Returns the raw file content with appropriate `Content-Type`. For text files (`.md`, `.json`, `.sql`, `.py`, `.txt`), returns `text/plain`. For binary files, returns `application/octet-stream`. Returns `404` if the file does not exist.

**`PUT /api/agents/{agent_id}/files/{path:path}`** — Create or update a file.

Accepts raw file content in the request body. Creates parent directories if they don't exist. If the agent has a running container, the change is visible immediately via the bind mount — identity file changes (`CLAUDE.md`, `SOUL.md`, `MEMORY.md`) take effect at the next context assembly (next message), no container restart needed. If the file being updated is `CLAUDE.md`, `SOUL.md`, or `MEMORY.md`, the orchestrator also updates the corresponding column in the `agents` table to keep the database in sync.

**`DELETE /api/agents/{agent_id}/files/{path:path}`** — Delete a file.

Returns `404` if the file does not exist. Refuses to delete identity files (`CLAUDE.md`, `SOUL.md`, `MEMORY.md`) — returns `403`. Refuses to delete directories (use a separate endpoint or require `?recursive=true` for safety).

### Component Topology

- **Frontend (Stateless UI)**: Single-page app. Connects to one WebSocket per session. Renders streaming tokens, tool call indicators, typing status. Has a "Clear Context" button and a file browser for viewing/editing agent workspace files.
- **Orchestrator (FastAPI)**: Central process. Manages WebSocket connections, SQLite state, container lifecycle, message routing, scheduled task queue, and inter-agent routing.
- **Worker Agents (Podman containers)**: One container per active agent. Rootless, no exposed ports. Each has a bind-mounted agent workspace directory for file-based IPC, persistent memory, and identity files. Runs a Python process using the Claude Agent SDK.
- **Embedding Service (Ollama container)**: Long-lived singleton container running an Ollama instance with a pulled embedding model. Workers call it over HTTP (`http://ollama:11434/api/embed`) on the shared Podman network to generate and query embeddings. Not per-session — shared by all workers.

### Container Lifecycle

- **Session Start**: Orchestrator looks up the agent's `host_dir` from the `agents` table and spawns a Podman container via `asyncio.create_subprocess_exec`, bind-mounting that directory to `/workspace`. The agent's workspace is persistent and shared across all sessions for that agent — `worker_db.sqlite`, `memory/`, `sessions/`, and identity files (`CLAUDE.md`, `SOUL.md`, `MEMORY.md`) survive container restarts. Container runs a long-lived polling loop. Orchestrator holds a reference to the async subprocess (pid, stdout pipe). Container ID is obtained via `--cidfile` flag (not `podman inspect`, which races with startup).
- **Session Active**: Both sides run 0.5s polling loops. Worker polls for `input.json`, processes all messages in the batch, deletes the file, and streams JSONL to stdout. Orchestrator polls for `input.json` deletion (ACK) and `QUEUED` message flushing, and separately reads stdout via async `readline()` to forward events to the WebSocket.
- **Session Idle** (no messages for 10 min): Container remains alive (no cold-start penalty on next message). Memory summarization is not triggered on idle — it occurs on session end or context overflow (see Memory Management Flow). If the session remains idle for the max idle TTL (default: 2 hours), the Periodic Reaper triggers a graceful shutdown (see Periodic Reaper). The agent's workspace persists regardless — only the container is terminated.
- **Session End** (UI disconnect or explicit "Clear Context"): Orchestrator issues `podman stop`, then `podman kill` if unresponsive, then `podman rm -f` to clean up. The `--rm` flag is not used so that the container survives orchestrator crashes and can be discovered during boot recovery (see Orchestrator Boot Recovery). The agent's `host_dir` is never deleted on session end — it is the agent's persistent workspace across all sessions.

### Container Configuration

Containers are launched with the following constraints:

- `--network rhclaw-internal` — workers join a shared Podman network (`podman network create rhclaw-internal`). This provides outbound HTTP/HTTPS access (required for the Claude Agent SDK's `WebSearch` and `WebFetch` tools) and inter-container DNS resolution (workers reach the Ollama embedding service at `ollama:11434`). The shared network does not expose host-local services to workers — a compromised worker cannot reach ports on the host machine, only other containers on the same network (see Security & Blast Radius Isolation below).
- `--read-only` — root filesystem is read-only.
- `--label rhclaw.managed=true`, `--label rhclaw.agent_id=<id>`, `--label rhclaw.session_id=<id>` — labels for boot recovery container discovery (see Orchestrator Boot Recovery).
- `--memory 2g`, `--cpus 2`, `--pids-limit 256`
- `--tmpfs /tmp:rw,size=512m`, `--tmpfs /var/tmp:rw,size=64m`
- `-v <agent_host_dir>:/workspace:Z` — bind mount of the agent's persistent workspace directory (`data/agents/<agent_id>/`) for IPC, memory, identity files, and worker database.

Writable paths inside the container:

- `/workspace` (bind mount): `input.json`, `worker_db.sqlite`, `sessions/` (SDK session JSONL files), `memory/`, `agents.json` (read-only from worker's perspective)
- `/tmp`, `/var/tmp` (tmpfs): Python temp files, library caches
- `MEMORY.md`, `CLAUDE.md`, `SOUL.md` are **read-only identity files** set by the user/operator. The agent reads them at context assembly time but must never modify them.
- All other worker filesystem writes must be restricted to the paths listed above. `worker_db.sqlite` must reside inside `/workspace` for `--read-only` compatibility.

### Embedding Service (Ollama Container)

The Ollama container is a long-lived singleton, not per-session. The orchestrator starts it during boot (before accepting WebSocket connections) and stops it during shutdown.

- `--network rhclaw-internal` — same shared network as workers. Workers resolve it as `ollama:11434`.
- `--name ollama` — fixed container name for DNS resolution on the shared network.
- `--label rhclaw.managed=true` — included in boot recovery container discovery.
- `--memory 4g`, `--cpus 2` — embedding models are lightweight but need headroom for concurrent requests from multiple workers.
- `--read-only` with `--tmpfs /tmp:rw,size=1g` — Ollama needs temp space for model loading.
- `-v ollama-models:/root/.ollama:Z` — named Podman volume for persistent model storage. Avoids re-pulling models on container restart.
- No bind-mounted host directories. No access to any session's `/workspace`. The Ollama container is stateless from the application's perspective — it receives text, returns vectors.

On first boot (or when the model volume is empty), the orchestrator runs `podman exec ollama ollama pull <model>` to pull the configured embedding model. This is a one-time operation.

### Security & Blast Radius Isolation

Because worker agents can fetch arbitrary external URLs via the Claude Agent SDK's `WebSearch` and `WebFetch` tools, they are exposed to prompt injection from malicious web content. A crafted page could attempt to hijack the agent's instructions, exfiltrate context, or abuse tool access.

The mitigation strategy is **blast radius isolation** rather than network blocking. Each worker runs in a per-session rootless Podman container with strict boundaries:

- **Filesystem isolation**: `--read-only` root filesystem. The only writable paths are the `/workspace` bind mount (scoped to that agent's persistent workspace directory) and ephemeral `tmpfs` mounts (`/tmp`, `/var/tmp`). A compromised worker cannot read or write files belonging to other agents, other users, or the host machine.
- **Process isolation**: `--pids-limit 256` prevents fork bombs. The container runs rootless with no elevated capabilities.
- **Memory/CPU isolation**: `--memory 2g`, `--cpus 2` prevent resource exhaustion attacks from affecting the host or other containers.
- **Network isolation**: Workers join the `rhclaw-internal` Podman network, which provides outbound internet access and inter-container DNS (for reaching the Ollama embedding service). No ports are exposed on worker containers. The shared network does not route to host-local services — a compromised worker cannot reach ports on the host machine. The only communication channel back to the orchestrator is stdout (JSONL). The only other reachable container is the Ollama embedding service, which is a stateless HTTP API with no access to session data, credentials, or other workers.
- **Session ephemerality**: Containers are destroyed on session end. A compromised container does not persist beyond its session lifecycle. The agent's workspace directory is retained for memory and identity persistence, but it contains only that agent's conversation history and summaries — no credentials, no cross-agent data.
- **Orchestrator as trust boundary**: The orchestrator validates all JSONL events from workers. Delegation requests are routed through the orchestrator, not directly between containers. A compromised worker cannot directly address or inject messages into another worker's `input.json`.

The net effect: a prompt-injected agent can waste its own session's tokens and produce garbage output, but it cannot escape its container, access other sessions, or reach internal systems.

### Inter-Agent Communication Flow

All inter-agent delegation spawns ephemeral containers. The orchestrator never routes delegation requests to an existing session worker — this avoids context contamination and queuing contention. The orchestrator acts as a dumb switchboard: it does not understand the delegation payload or decide routing. The worker (the LLM) decides who to delegate to via its system prompt instructions.

1. Worker A emits a `delegate` event to stdout with the target agent type and a self-contained payload.
2. Orchestrator intercepts the delegate event from Worker A's stdout stream.
3. Orchestrator validates the `target` against the `agents` table by name (security boundary — prevents a prompt-injected worker from addressing arbitrary or nonexistent targets).
4. Orchestrator inserts a row into `active_delegations` with `status = 'pending'` and `timeout_at = now + 5 minutes`.
5. Orchestrator spawns a delegation container with the target agent type's base config (`CLAUDE.md`, `SOUL.md`). The container gets a temporary host directory — no user memory, no session history. The delegation payload must be self-contained. Updates `active_delegations` with the `container_id` and `status = 'running'`.
6. Orchestrator writes the delegation payload to the delegation container's `input.json`.
7. Orchestrator reads the delegation container's stdout, intercepts the `complete` event containing the `delegation_id` in metadata. Updates `active_delegations` with `status = 'completed'` and stores the result.
8. Orchestrator queues a `delegation_response` for Worker A and flushes to Worker A's `input.json` when ready.
9. Orchestrator destroys the delegation container and cleans up its temporary host directory.
10. Worker A receives the delegation response and continues processing.
11. If the delegation container crashes or times out, the orchestrator sets `active_delegations.status` to `failed` or `timed_out` and queues a `delegation_response` with error payload so Worker A can report the failure to the user.

The delegation container follows the same lifecycle as scheduled task containers: spawn, deliver input, read stdout, collect result, destroy. The `agent_containers` table distinguishes these via `container_type`: `delegation` containers get a temporary host directory with no agent data (the delegation payload must be self-contained), while `scheduled_task` containers bind-mount the agent's workspace directory because tasks like memory compaction need to read/write that agent's files (see Data Models).

### SDK Subagents vs. Worker Delegation

The Claude Agent SDK supports subagent definitions within a single `query()` call. These are internal to a worker — a researcher worker might spawn a subagent for focused web search or summarization. SDK subagents run in the same process, share the same container, and are invisible to the orchestrator. They are an implementation detail of the worker, not part of the inter-agent communication architecture.

Worker-to-worker delegation (described above) is for cross-container, cross-capability communication where blast radius isolation matters.

### Orchestrator Boot Recovery

If the orchestrator process crashes or the host reboots, messages marked `IN-FLIGHT` in `message_queue` are orphaned — the worker that was supposed to process them may still be running (orchestrator crash) or gone (host reboot), and the flush logic only looks for `QUEUED` messages. On startup, before accepting WebSocket connections, the orchestrator runs state reconciliation. The ordering of these steps is critical — containers must be killed before files are touched, because workers are separate Podman processes that survive an orchestrator crash.

Containers are launched with `--label rhclaw.managed=true --label rhclaw.agent_id=<id> --label rhclaw.session_id=<id>` so the orchestrator can identify its own containers on recovery.

1. Connect to SQLite.
2. Run `podman ps -a --filter label=rhclaw.managed=true -q` to find all managed containers (running or stopped).
3. Run `podman rm -f <id>` for each. After this step, no workers are running — all subsequent file operations are safe.
4. Execute: `UPDATE message_queue SET status = 'QUEUED', flushed_at = NULL WHERE status = 'IN-FLIGHT';`
5. Delete all `input.json` files in agent workspace directories (`data/agents/*/input.json`). Safe because step 3 guarantees no worker is mid-read.
6. Set all `agent_containers` rows with status `running`, `starting`, or `stopping` to `stopped`.
7. Clean up any orphaned delegation container host directories (`container_type = 'delegation'`).
8. Mark all in-flight delegations as failed: `UPDATE active_delegations SET status = 'failed' WHERE status IN ('pending', 'running');`
9. Ensure the `rhclaw-internal` Podman network exists (`podman network create rhclaw-internal` — idempotent, errors if already exists, ignored).
10. Start the Ollama embedding container. If the model volume is empty, pull the configured embedding model (`podman exec ollama ollama pull <model>`). Wait for the Ollama HTTP API to become ready before proceeding.

When the orchestrator resumes normal operation and new WebSocket connections arrive, containers are respawned and the re-queued messages are batched into fresh `input.json` files. Workers must deduplicate by `message_id` to guarantee at-least-once delivery without double-processing (see `processed_messages` table in Worker SQLite Schema).

### Container Crash Recovery

1. The JSONL stream reader yields a fatal `system_error` event when it detects unexpected EOF (non-zero exit code from worker process).
2. The orchestrator forwards the error to the client WebSocket and updates `agent_containers.status` to `error` in the database.
3. Orchestrator runs `podman rm -f` to clean up the dead container.
4. If the WebSocket is still connected, the orchestrator respawns the container for the same agent (mounting the same `host_dir`), restarts the stdout reader, and notifies the client.
5. If the WebSocket is disconnected, the crash is logged but no respawn occurs.
6. Circuit breaker: if 3+ crashes occur within 10 minutes for the same session, the session is marked as `error` and retrying stops. The client is notified that the agent is unavailable.

### Periodic Reaper

The orchestrator runs a single background reaper task (every 30 seconds) that enforces timeouts and idle TTLs:

- **Delegation timeout**: Queries `active_delegations` for rows with `status = 'running'` and `timeout_at < now`. Kills the delegation container, sets `status = 'timed_out'`, queues a `delegation_response` with error payload to the source worker. Default timeout: 5 minutes (set in `active_delegations.timeout_at` at creation time).
- **Scheduled task timeout**: Queries `scheduled_tasks` for rows with `status = 'running'` that have exceeded their `timeout_seconds`. Kills the container. If `retry_count < max_retries`, re-queues the task as `pending` with incremented `retry_count`. Otherwise marks as `failed`. Default timeout: 15 minutes (configurable per `task_type`).
- **Session max idle TTL**: Queries `agent_containers` for session containers with `last_activity` older than the max idle TTL (default: 2 hours). Sends a `shutdown` system command via `input.json` to let the worker run session-end summarization gracefully, with a 60-second grace period. If the worker doesn't emit `done` within the grace period, force-kills the container. Host directory is retained for memory persistence.

Both the idle grace period (10 minutes, existing behavior — no action taken) and the max idle TTL (2 hours, triggers shutdown) are configurable constants.

---

## 2. Data Models

### Orchestrator SQLite Schema

```sql
-- User-created agent instances (persistent identity + workspace)
CREATE TABLE agents (
    id          TEXT PRIMARY KEY,  -- UUID
    name        TEXT NOT NULL UNIQUE,  -- user-facing name (e.g., "coder", "researcher", "bob")
    agent_type  TEXT NOT NULL DEFAULT 'default',  -- references agent_templates/ for seed files
    host_dir    TEXT NOT NULL,     -- absolute path to persistent workspace (e.g., data/agents/<id>/)
    claude_md   TEXT,             -- user-customized CLAUDE.md content (NULL = use agent_type default)
    soul_md     TEXT,             -- user-customized SOUL.md content (NULL = use agent_type default)
    memory_md   TEXT,             -- user-customized MEMORY.md content (NULL = use agent_type default)
    container_memory TEXT NOT NULL DEFAULT '2g',  -- podman --memory flag
    container_cpus   TEXT NOT NULL DEFAULT '2',   -- podman --cpus flag
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    status      TEXT NOT NULL DEFAULT 'active'  -- active | archived
);

-- Conversation sessions
CREATE TABLE sessions (
    id          TEXT PRIMARY KEY,  -- UUID
    agent_id    TEXT NOT NULL REFERENCES agents(id),  -- which agent instance owns this session
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    ended_at    TEXT,
    status      TEXT NOT NULL DEFAULT 'active'  -- active | idle | terminated
);

-- All messages (source of truth)
CREATE TABLE messages (
    id          TEXT PRIMARY KEY,  -- UUID
    session_id  TEXT NOT NULL REFERENCES sessions(id),
    role        TEXT NOT NULL,     -- user | assistant | system | tool
    content     TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    metadata    TEXT  -- JSON: token count, model, latency, etc.
);
CREATE INDEX idx_messages_session ON messages(session_id, created_at);

-- Container state tracking
CREATE TABLE agent_containers (
    id              TEXT PRIMARY KEY,  -- UUID
    agent_id        TEXT NOT NULL REFERENCES agents(id),  -- which agent instance this container serves
    session_id      TEXT NOT NULL REFERENCES sessions(id),
    container_id    TEXT,              -- podman container ID (set after launch)
    pid             INTEGER,           -- OS process ID of the podman run process
    container_type  TEXT NOT NULL DEFAULT 'session',  -- session | delegation | scheduled_task
    status          TEXT NOT NULL DEFAULT 'starting',  -- starting | running | idle | stopping | stopped | error
    started_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    stopped_at      TEXT,
    last_activity   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    error_message   TEXT
);
CREATE INDEX idx_agent_containers_agent ON agent_containers(agent_id);
CREATE INDEX idx_agent_containers_session ON agent_containers(session_id);
CREATE INDEX idx_agent_containers_status ON agent_containers(status);

-- Scheduled tasks
CREATE TABLE scheduled_tasks (
    id              TEXT PRIMARY KEY,  -- UUID
    agent_id        TEXT NOT NULL REFERENCES agents(id),     -- links task to agent's host_dir for /workspace bind mount
    agent_type      TEXT NOT NULL,     -- which agent handles this
    task_type       TEXT NOT NULL,     -- e.g., "data_refresh", "cleanup"
    payload         TEXT NOT NULL,     -- JSON
    scheduled_at    TEXT NOT NULL,     -- when to execute
    status          TEXT NOT NULL DEFAULT 'pending',  -- pending | running | completed | failed
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    completed_at    TEXT,
    result          TEXT,             -- JSON
    retry_count     INTEGER NOT NULL DEFAULT 0,
    max_retries     INTEGER NOT NULL DEFAULT 3,
    timeout_seconds INTEGER NOT NULL DEFAULT 900  -- 15 minutes; configurable per task_type
);
CREATE INDEX idx_scheduled_tasks_status ON scheduled_tasks(status, scheduled_at);
CREATE INDEX idx_scheduled_tasks_agent ON scheduled_tasks(agent_id);

-- Delegation tracking
CREATE TABLE active_delegations (
    delegation_id     TEXT PRIMARY KEY,  -- from the delegate event
    source_session_id TEXT NOT NULL REFERENCES sessions(id),
    source_message_id TEXT NOT NULL,     -- message_id from the delegate event
    target_agent_type TEXT NOT NULL,
    container_id      TEXT REFERENCES agent_containers(id),
    status            TEXT NOT NULL DEFAULT 'pending',  -- pending | running | completed | failed | timed_out
    payload           TEXT NOT NULL,     -- JSON: the delegation request payload
    result            TEXT,              -- JSON: the delegation response payload
    timeout_at        TEXT NOT NULL,     -- absolute deadline (default: created_at + 5 minutes)
    created_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    completed_at      TEXT
);
CREATE INDEX idx_active_delegations_status ON active_delegations(status);
CREATE INDEX idx_active_delegations_timeout ON active_delegations(status, timeout_at);

-- IPC message queue (orchestrator -> worker delivery)
CREATE TABLE message_queue (
    id          TEXT PRIMARY KEY,     -- UUID, canonical message identifier
    session_id  TEXT NOT NULL REFERENCES sessions(id),
    payload     TEXT NOT NULL,        -- JSON: minimal IPC message (type-specific fields only, see IPC Data Contract);
                                     -- queue_message() enforces payload.message_id == id at insertion time
    status      TEXT NOT NULL DEFAULT 'QUEUED',  -- QUEUED | IN-FLIGHT | PROCESSED
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    flushed_at  TEXT,                 -- when written to input.json
    processed_at TEXT                 -- when worker deleted input.json
);
CREATE INDEX idx_message_queue_flush ON message_queue(session_id, status, created_at);
```

### Worker SQLite Schema (worker_db.sqlite per agent)

```sql
-- FTS5 table for BM25 keyword search
CREATE VIRTUAL TABLE message_fts USING fts5(
    content,
    role,
    session_id UNINDEXED,
    timestamp UNINDEXED,
    tokenize='porter unicode61'
);

-- Vector embeddings table (sqlite-vec)
-- Stores embeddings for semantic similarity search
CREATE VIRTUAL TABLE message_vec USING vec0(
    embedding float[1024],  -- must match Ollama embedding model output dimension;
                            -- changing the Ollama model requires rebuilding this table
    +content TEXT,
    +role TEXT,
    +session_id TEXT,
    +timestamp TEXT
);

-- Deduplication for at-least-once delivery (boot recovery)
CREATE TABLE processed_messages (
    message_id  TEXT PRIMARY KEY      -- tracks which message_ids have been processed
);

-- Daily memory file index (upserted when a session summary is appended)
CREATE TABLE memory_files (
    id          TEXT PRIMARY KEY,
    date        TEXT NOT NULL,        -- YYYY-MM-DD
    file_path   TEXT NOT NULL UNIQUE, -- e.g., memory/2026-04-01.md, memory/2026-04-01-2.md
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX idx_memory_files_date ON memory_files(date);
```

### Schema Migration

Both the orchestrator and worker databases use a `schema_version` table to track applied migrations:

```sql
CREATE TABLE IF NOT EXISTS schema_version (
    version     INTEGER NOT NULL,
    applied_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
```

On boot, the orchestrator (and the worker on container startup) reads the current max version, then applies numbered SQL migration files sequentially from a `migrations/` directory (e.g., `001_initial.sql`, `002_add_delegations.sql`). Each migration is wrapped in a transaction. Files are idempotent where possible (`CREATE TABLE IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS`). No external dependencies (no Alembic) — SQLite's limited `ALTER TABLE` support means most migrations are simple additions, and the few that aren't require the create-copy-drop-rename pattern regardless of tooling.

---

## 3. IPC Data Contract

### input.json (Orchestrator -> Worker)

The orchestrator runs a 0.5s polling loop per active session that handles both ACK detection and message flushing. Each tick: (1) if `IN-FLIGHT` messages exist and `input.json` is gone, mark them `PROCESSED` — the worker has ACK'd by deleting the file. (2) If `QUEUED` messages exist and no `input.json` exists, batch all `QUEUED` messages into a single `input.json` array (ordered by `created_at`), mark them `IN-FLIGHT`, and write using the Atomic Write Protocol (below). The worker's own 0.5s polling loop detects `input.json`, reads it, processes all messages in order, and deletes the file (ACK). The orchestrator is the single writer, and the file lifecycle is the complete IPC protocol — stdout carries only response data, never ACK signals. This eliminates race conditions.

#### Atomic Write Protocol

All writes to `input.json` must follow this protocol to prevent corrupt or zero-length files:

1. Create the temp file **in the same directory** as `input.json` (e.g., `input.json.tmp.<pid>`). `os.rename` is atomic only when source and destination are on the same filesystem. Writing to `/tmp` or any other mount and then renaming across filesystems falls back to a non-atomic copy+delete, which can produce a partially-written `input.json` if the process crashes mid-copy.
2. Write the full JSON payload to the temp file.
3. Call `os.fsync(fd)` on the temp file's file descriptor before closing. Without `fsync`, the kernel may reorder the write and the rename — a power failure after rename but before the write is flushed to disk produces a zero-length or corrupt `input.json`.
4. Close the temp file.
5. Call `os.rename(temp_path, input_json_path)`. This is an atomic operation on POSIX filesystems when both paths are on the same mount.
6. **Cleanup on failure**: The entire sequence must be wrapped in `try...finally`. If any step (write, fsync, rename) raises an exception, the `finally` block must remove the temp file (`os.unlink`, ignoring `FileNotFoundError`) before re-raising. Leaked temp files are harmless but wasteful; a partially-written `input.json` is a data-loss bug.

The file contains a JSON array of message objects. Each message carries only the fields the worker needs — the worker already knows its own `session_id`, `role` is derivable from `type`, and context retrieval is handled worker-side.

**User message**:
```jsonc
{"message_id": "uuid-v4", "type": "user_message", "content": "Explain how async works in Python", "timestamp": "2026-04-01T12:00:00Z"}
```

**Delegation request** (delivered to an ephemeral delegation container):
```jsonc
{"message_id": "uuid-v4", "type": "delegation_request", "content": "Find papers on RLHF", "delegation_id": "del-uuid", "timestamp": "2026-04-01T12:00:00Z"}
```

**Delegation response** (delivered back to the source worker):
```jsonc
{"message_id": "uuid-v4", "type": "delegation_response", "content": "Found 3 relevant papers...", "delegation_id": "del-uuid", "timestamp": "2026-04-01T12:00:05Z"}
```

**System command** (idempotent, no `message_id` needed):
```jsonc
{"type": "system_command", "command": "clear_context", "timestamp": "2026-04-01T12:00:00Z"}
```

**Batched example** (3 rapid-fire user messages + a pending delegation response):
```jsonc
[
    {"message_id": "aaa-111", "type": "user_message", "content": "Hey, quick question", "timestamp": "2026-04-01T12:00:00Z"},
    {"message_id": "bbb-222", "type": "user_message", "content": "How does async work?", "timestamp": "2026-04-01T12:00:01Z"},
    {"message_id": "ccc-333", "type": "user_message", "content": "Specifically the event loop", "timestamp": "2026-04-01T12:00:02Z"},
    {"message_id": "ddd-444", "type": "delegation_response", "content": "Found 3 papers on RLHF...", "delegation_id": "del-uuid", "timestamp": "2026-04-01T12:00:03Z"}
]
```

### stdout JSONL (Worker -> Orchestrator)

Each line is a self-contained JSON object. The orchestrator parses line-by-line, discards non-JSON lines (library noise), and routes valid events to the WebSocket or delegation handler.

**Token event** (streaming LLM output):
```json
{"type": "token", "content": "The", "message_id": "uuid-v4", "seq": 1}
```

**Status event** (lifecycle signals):
```json
{"type": "status", "status": "thinking", "message_id": "uuid-v4"}
```
Valid statuses: `thinking`, `generating`, `tool_calling`, `done`, `error`, `idle`, `context_cleared`

**Tool call event** (agent using a tool):
```json
{"type": "tool_call", "tool_name": "bash", "tool_input": {"command": "ls -la"}, "tool_call_id": "tc-uuid", "message_id": "uuid-v4"}
```

**Tool result event**:
```json
{"type": "tool_result", "tool_call_id": "tc-uuid", "output": "file1.txt\nfile2.py", "message_id": "uuid-v4"}
```

**Delegation event** (inter-agent):
```json
{"type": "delegate", "target": "agent_researcher", "payload": {"task": "Find papers on RLHF"}, "delegation_id": "del-uuid", "message_id": "uuid-v4"}
```

**System error event**:
```json
{"type": "system_error", "error": "Out of memory", "fatal": false, "message_id": "uuid-v4"}
```

**Complete message event** (full assembled response, sent after streaming completes):
```json
{"type": "complete", "content": "The full assembled response text...", "message_id": "uuid-v4", "usage": {"input_tokens": 1500, "output_tokens": 342}}
```

**Task result event** (emitted by ephemeral workers running scheduled tasks):
```json
{"type": "task_result", "task_id": "uuid-v4", "status": "success", "payload": {"summaries_compacted": 7}, "message_id": "uuid-v4"}
```
```json
{"type": "task_result", "task_id": "uuid-v4", "status": "failed", "payload": {}, "error": "Embedding service unreachable", "message_id": "uuid-v4"}
```

The orchestrator's stream reader intercepts `task_result` events, writes `payload` to `scheduled_tasks.result`, sets `completed_at` and `status`, and then destroys the ephemeral container.

---

## 4. Memory Management Flow

### Agent Workspace & Identity Files

When a user creates an agent, the orchestrator:

1. Creates a persistent workspace directory at `data/agents/<agent_id>/`.
2. Seeds it with identity files from `agent_templates/<agent_type>/` (or from user-provided content in the `agents` table if customized): `CLAUDE.md`, `SOUL.md`, `MEMORY.md`.
3. Creates empty subdirectories: `sessions/`, `memory/`.

The workspace layout:

- `data/agents/<agent_id>/CLAUDE.md` — agent instructions and behavioral rules.
- `data/agents/<agent_id>/SOUL.md` — agent personality and communication style.
- `data/agents/<agent_id>/MEMORY.md` — persistent identity context (who the agent is, who the user is, special preferences). This is not a log or summary dump.
- `data/agents/<agent_id>/sessions/` — SDK session JSONL files.
- `data/agents/<agent_id>/memory/` — daily memory summary files.
- `data/agents/<agent_id>/worker_db.sqlite` — worker database (FTS, vectors, deduplication).
- `data/agents/<agent_id>/agents.json` — manifest of all other agents available for delegation (written by the orchestrator).

Identity files are read-only from the worker's perspective. The agent reads them at context assembly but must never modify them. If the user updates an agent's identity files via the UI, the orchestrator writes the new content to the `agents` table and to the workspace directory on disk. Changes take effect on the next container spawn (not mid-session).

### Agent Discovery

Workers need to know which other agents exist in order to decide delegation targets. The orchestrator writes an `agents.json` manifest to each agent's workspace directory. The file contains an array of all agents except the current one:

```json
[
  {"name": "coder", "description": "Writes and debugs code", "agent_type": "coder"},
  {"name": "researcher", "description": "Finds and summarizes information", "agent_type": "researcher"}
]
```

The orchestrator writes/refreshes `agents.json`:

- At container spawn time (guaranteed fresh on every startup).
- When an agent is created or deleted — the orchestrator updates `agents.json` in all active agent workspace directories. For agents with a running container, the update is picked up at the worker's next context assembly. No `system_command` is needed — the worker reads the file from disk each time.

The worker reads `/workspace/agents.json` at context assembly time and includes the available agents in the system prompt so the LLM knows who it can delegate to. This file is read-only from the worker's perspective. The data is non-sensitive (names and descriptions only, no workspace paths or credentials), so there is no isolation concern.

### Session Storage

Session history is managed by the Claude Agent SDK's native session persistence. The SDK stores sessions as JSONL files. The worker configures the SDK's session storage path to write to `/workspace/sessions/` (the bind mount). Since the workspace is per-agent and persists across sessions, all session JSONL files accumulate in the same directory. The worker uses `resume: sessionId` on subsequent `query()` calls to maintain conversation continuity within a session.

### On Message Receipt (Context Retrieval)

1. Worker reads `input.json` and iterates through the message array.
2. **Batch consolidation**: The worker appends all `user_message` entries to its internal conversation buffer. Non-user messages (`delegation_response`, `system_command`) are handled immediately as they are encountered. For `user_message` entries, the worker checks `message_id` against the `processed_messages` table in `worker_db.sqlite` and skips duplicates (at-least-once delivery safety).
3. For the final user message in the batch, generate an embedding by calling the Ollama container (`POST http://ollama:11434/api/embed`). Earlier messages in a rapid-fire batch are typically corrections or continuations — the last message best represents the user's current intent for retrieval purposes. All messages still enter the conversation buffer and are visible to the LLM.
4. Execute hybrid search against `worker_db.sqlite`:
   - BM25 keyword search via FTS5 (top 20 by rank).
   - Semantic vector search via sqlite-vec (top 20 by distance).
5. Merge results using Reciprocal Rank Fusion (RRF):
   - `score(doc) = sum(1 / (k + rank_in_list))` for each list containing the doc.
   - `k = 60` (standard RRF constant).
   - Deduplicate by deterministic content hash (`hashlib.md5`, not Python's `hash()`).
6. Take top 10 results as retrieved context.
7. Read `MEMORY.md` for permanent identity context (always included in full, never truncated).
8. Query `memory_files` table in `worker_db.sqlite` to find relevant daily memory files by date. Read matching files from disk, loading most recent dates first. Total memory content is capped at a configurable token budget (e.g., 4000 tokens) — once the budget is exhausted, older dates are not loaded. This prevents memory from crowding out the conversation and retrieved context.
9. Construct a single Claude Agent SDK call:
   - System prompt = `CLAUDE.md` + `SOUL.md`
   - Injected context = `MEMORY.md` + relevant daily memory content + RRF top-10 results
   - User message = consolidated batch content
   - Session = `resume: sessionId` (SDK-native session continuity)
10. Stream the response as JSONL to stdout.
11. After response completes:
    - Store user message + assistant response in `message_fts` and `message_vec` (embedding generated via Ollama).
    - Insert processed `message_id`s into `processed_messages` table.
    - Update `last_activity` timestamp.

### Context Overflow (Session Split)

The worker monitors the assembled context size before each Claude API call. When the context exceeds 80% of the model's context window:

1. Worker summarizes the current session by calling Claude with the full session content and a summarization prompt.
2. Worker appends the summary to the daily memory file `memory/<YYYY-MM-DD>.md`, titled with the source session filepath (e.g., `sessions/<timestamp>.md`).
3. If the daily memory file exceeds a size threshold, the worker creates a continuation file: `memory/<YYYY-MM-DD>-2.md`, `memory/<YYYY-MM-DD>-3.md`, etc.
4. **Compaction trigger**: If a day would exceed 3 continuation files (i.e., `-4.md` would be created), the worker compacts instead: reads all files for that date, calls Claude with a distillation prompt to compress them into a single coherent summary, replaces all files with a single `memory/<YYYY-MM-DD>.md`, and deletes the continuation files. Updates the `memory_files` table accordingly.
5. Worker upserts the daily memory file entry in the `memory_files` table in `worker_db.sqlite` (date + file path).
6. Worker starts a new SDK session (new `sessionId`), seeded with the relevant content from the previous session's summary as injected context.
7. The session split is invisible to the user — the WebSocket connection and orchestrator session remain unchanged. Only the worker's internal SDK session rotates.

### On Session End

When a session ends (UI disconnect or "Clear Context"):

1. Worker summarizes the current session content.
2. Worker appends the summary to `memory/<YYYY-MM-DD>.md`, titled with the source session filepath.
3. If the daily memory file exceeds the size threshold, a continuation file is created.
4. Worker upserts the daily memory file entry in the `memory_files` table.
5. Worker emits `done` status to stdout.

---

## 5. Project Structure

- `orchestrator/` — FastAPI application
  - `main.py` — App entrypoint, lifespan events
  - `routes.py` — WebSocket, HTTP, and admin endpoints
  - `container_manager.py` — Podman lifecycle (spawn, stop, kill)
  - `stream_reader.py` — JSONL stdout parser
  - `ipc.py` — Message queue + atomic file writer
  - `db.py` — SQLite operations (aiosqlite)
  - `delegation.py` — Inter-agent routing
  - `scheduler.py` — Scheduled task runner
  - `models.py` — Pydantic schemas for IPC data contracts
  - `migrations/` — Numbered SQL migration files (e.g., `001_initial.sql`)
- `worker/` — Container-side agent code
  - `worker.py` — Main polling loop + JSONL emitter
  - `memory.py` — Hybrid search, indexing, summarization
  - `agent.py` — Claude Agent SDK integration (including SDK subagent definitions, which are internal to the worker and invisible to the orchestrator)
  - `migrations/` — Numbered SQL migration files for worker_db.sqlite
  - `Containerfile` — Podman image definition
- `data/agents/<agent_id>/` — Per-agent persistent workspace (created when user creates an agent)
  - `CLAUDE.md`, `SOUL.md`, `MEMORY.md` — identity files (seeded from templates, updatable via UI)
  - `agents.json` — manifest of available delegation targets (written by orchestrator)
  - `sessions/` — SDK session JSONL files
  - `memory/` — daily memory summary files
  - `worker_db.sqlite` — worker database
- `agent_templates/` — Seed templates for new agents, one subdirectory per agent type
  - `default/CLAUDE.md`
  - `default/SOUL.md`
  - `default/MEMORY.md`
- `web/` — Stateless web UI (Vite + React + TypeScript)
  - Built with shadcn/ui preset `b2BoX62hm` (`npx shadcn@latest init --preset b2BoX62hm --template vite`)
  - Style: `radix-vega`, base color: `zinc`, icon library: `lucide`
  - Font: Geist Variable (via `@fontsource-variable/geist`)
  - Border radius: `0.625rem`
  - Primary color: teal/green (`oklch(0.508 0.118 165.612)` light, `oklch(0.432 0.095 166.913)` dark)
  - Full theme variables are defined in `web/src/index.css`
  - All UI components must use shadcn/ui components and follow this preset's design tokens
- `tests/` — Test suite

---

## 6. Tool Execution Ownership

- Workers natively execute the Claude Agent SDK's built-in tools inside the container, including `WebSearch`, `WebFetch`, `bash`, and file operations. These tools run with the container's network and filesystem access — outbound HTTP/HTTPS is available, but filesystem writes are restricted to `/workspace`.
- The orchestrator never executes tools — it only routes messages and manages container lifecycle.
- **Privileged tool brokering**: Tools that access internal systems (databases, user email, internal APIs, credentials stores) must not be executed directly inside the web-facing worker container. A prompt-injected agent with direct access to an internal database could exfiltrate or corrupt data beyond its session boundary. Instead, privileged tools should be brokered through a Model Context Protocol (MCP) server or host-level proxy that enforces its own authorization, rate limiting, and audit logging independent of the worker. The worker calls these tools via the SDK's MCP integration; the MCP server validates the request against the session's permission scope before executing it.

---

## 7. Key Design Decisions and Rationale

1. **File-based input (polling) over stdin pipe**: stdin requires careful framing and can deadlock if the buffer fills. File-based input with atomic rename is simple and debuggable (you can `cat input.json`). The orchestrator's SQLite `message_queue` table handles backpressure — messages are queued as `QUEUED`, batched into `input.json` only when the worker is ready (file doesn't exist), and marked `PROCESSED` after the worker deletes it. The orchestrator is the single writer, eliminating race conditions. Durability is enforced by the Atomic Write Protocol (Section 3): same-directory temp file, `os.fsync` before rename, `try...finally` cleanup.

2. **JSONL over stdout vs. socket/HTTP**: No network ports exposed on containers (security). stdout is the simplest zero-config IPC channel. JSONL is self-framing (one object per line), so no custom protocol needed.

3. **asyncio.create_subprocess_exec over Podman Python SDK**: Async subprocess is dependency-free, transparent (you can reproduce commands manually), and gives direct access to stdout pipe without blocking the event loop. The Podman SDK adds complexity without proportional value for this use case.

4. **SQLite over PostgreSQL**: Single-node deployment. SQLite with WAL mode handles the concurrency needs. No ops overhead. Can migrate to PostgreSQL later if needed — the schema is standard SQL.

5. **Hybrid search (BM25 + vectors) over pure vector search**: BM25 catches exact keyword matches that embeddings miss (e.g., error codes, function names). Vector search catches semantic similarity. RRF fusion gets the best of both without tuning weights.

6. **Containers stay alive during session**: Cold-starting a container for every message adds 2-5 seconds of latency. Keeping them alive trades ~50MB memory per container for sub-second response initiation.

---

## 8. Future Improvements

- **Session file retention policy**: SDK session JSONL files in `sessions/` will accumulate over time. Daily memory files capture the distilled signal, so session files older than a configurable threshold (e.g., 30 days) could be pruned. The daily memory files in `memory/` are the durable record.
- **Embedding vector pruning**: Vectors for individual messages older than a configurable threshold could be pruned from `message_vec`, since daily memory summaries retain the semantic signal at a higher level.
- **Ollama health check mechanism**: Boot recovery step 10 requires waiting for the Ollama HTTP API to become ready, but no concrete mechanism is specified. Implement a polling check against `GET http://ollama:11434/` with exponential backoff and a maximum retry count, or use Podman's `--health-cmd` flag to let the container runtime manage readiness.
- **Delegation circuit breaker**: Container crashes have a circuit breaker (3 crashes in 10 minutes), but delegation has no equivalent. A worker could repeatedly delegate to a failing agent type, spawning and killing containers in a loop. Add a per-agent-type failure threshold that temporarily blocks delegation to that target after N consecutive failures.
- **Delegation concurrency cap**: There is no limit on concurrent delegation containers. A runaway or compromised worker could emit `delegate` events in a tight loop, exhausting host resources. Add a per-session and/or global cap on active delegations, rejecting new requests with an error payload when the limit is reached.
- **Asynchronous memory compaction**: Memory compaction currently runs inline during context overflow handling, adding latency to the user's next response. Offload compaction to a scheduled task (the infrastructure already exists) so the worker can immediately start a new session with the uncompacted summaries and compact in the background.
- **Ollama embedding failure resilience**: The context retrieval flow calls Ollama for embeddings without a documented failure path. If the Ollama container is temporarily unavailable (restart, OOM), the worker should retry with backoff and fall back to BM25-only search rather than crashing or skipping retrieval entirely.
- **`processed_messages` pruning**: The `processed_messages` table grows unboundedly since every message ID is inserted and never deleted. Its only purpose is boot recovery deduplication, so rows older than the most recent orchestrator boot timestamp could be safely pruned on worker startup.
- **WAL mode activation**: SQLite WAL mode is referenced as a design decision (Section 7) but is not documented as a startup step. Both the orchestrator and worker should execute `PRAGMA journal_mode=WAL` on database connection, either as an explicit startup step or as part of the first migration.
- **Ollama container type in `agent_containers`**: The `container_type` column only covers `session | delegation | scheduled_task`. The Ollama container is labeled `rhclaw.managed=true` and discovered during boot recovery, but has no representation in the `agent_containers` table. Either add a `singleton` container type or track the Ollama container in a separate mechanism (e.g., a config row or in-memory reference).
- **Graceful orchestrator shutdown**: Currently every orchestrator restart triggers the crash recovery path. Implement a clean shutdown sequence: stop accepting new WebSocket connections, signal active workers to summarize and exit via `system_command: shutdown`, wait with a configurable timeout for workers to emit `done`, then force-kill remaining containers and close the database.
