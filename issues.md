# Known Issues

## Critical: Concurrency & Race Conditions (FIXED)

Issues 1-3, 5 have been fixed by adding `asyncio.Lock` on `_active_workers`, awaiting task cancellation before creating replacements, and re-keying `_inflight_source` from session-level to message-level. Issue 4 was determined to be safe due to DB-level status guards.

### 1. No synchronization on `_active_workers` dict -- FIXED

**File:** `orchestrator/routes.py`

The shared `_active_workers` dict is read and mutated from multiple async tasks (WebSocket handler, monitor, cleanup, shutdown, scheduler) with no `asyncio.Lock`. Multiple code paths can pop the same worker, replace entries mid-iteration, or read stale state.

**Impact:** Worker state corruption, double cleanup, orphaned containers, missed crash recovery.

**Fix:** Wrap all access in an `asyncio.Lock`. `get_active_workers()` at line 1078 exposes the raw dict to the scheduler -- return a snapshot copy instead.

### 2. Task cancellation without await -- FIXED

**File:** `orchestrator/routes.py`

Every cleanup path does `worker.polling_task.cancel()` then immediately proceeds without awaiting the task's completion. The cancelled task may still be mid-`atomic_write()` or mid-DB-transaction when the new polling loop starts.

**Impact:** Two polling loops running concurrently on the same session, corrupting `input.json` and `response.json`.

**Fix:** After `cancel()`, do `await asyncio.gather(task, return_exceptions=True)` before starting new tasks.

### 3. TOCTOU on `response.json` -- FIXED (via #2)

**File:** `orchestrator/ipc.py`

The polling loop checks `response_path.exists()`, reads it, then deletes it. If the old polling loop (not yet fully cancelled, see #2) races with the new one, both process the same events.

**Impact:** Duplicate message processing, double token emissions to WebSocket.

### 4. Scheduler task dequeue race -- NOT A BUG

**File:** `orchestrator/scheduler.py`

`_running_tasks` and `_running_agentic` are checked without locks. Between the DB query and the `if task_id in _running_tasks` check, another tick could start the same task.

**Impact:** Mitigated by DB-level status transition (`pending` -> `running`) before `await`. The `_running_tasks`/`_running_agentic` dicts are populated synchronously before any yield point.

### 5. `_inflight_source` dict unsynchronized -- FIXED

**File:** `orchestrator/ipc.py`

The metadata dict tracking scheduled task source info is written/cleared without synchronization across concurrent polling loops for different sessions.

**Impact:** Scheduled task results attributed to the wrong task or lost entirely.

---

## High: Logic Bugs

### 6. WebSocket handler missing general exception handler

**File:** `orchestrator/routes.py` (line ~1229)

Only `WebSocketDisconnect` is caught. Any other exception (DB error, JSON parsing, validation) kills the handler without calling `_cleanup_session()`.

**Impact:** Leaked tasks, orphaned workers, sessions stuck in active state.

**Fix:** Add `except Exception` that calls cleanup before re-raising.

### 7. `_store_message` has no error handling on `queue_message()`

**File:** `orchestrator/routes.py` (line 835)

The message is committed to the `messages` table, then `queue_message()` is called separately. If the second operation fails, the message exists in the DB but is never queued for delivery.

**Impact:** User messages silently lost -- stored but never delivered to the worker.

### 8. Worker deduplication is not atomic

**File:** `worker/worker.py` (lines 91-104, 226-229)

`_is_processed()` and `_mark_processed()` are separate calls. Two concurrent `process_message` invocations with the same `message_id` can both pass the check.

**Impact:** Duplicate message processing, double API calls.

**Fix:** Use `INSERT OR IGNORE` + check `changes()` in a single operation, or `BEGIN IMMEDIATE`.

### 9. Memory compaction off-by-one

**File:** `worker/memory.py` (lines 273-279)

`if seq > MAX_CONTINUATION_FILES` triggers compaction after creating the 4th file, not before. One more file than intended is created before compaction kicks in.

### 10. Wrong error code for JSON parse failures

**File:** `orchestrator/routes.py` (lines ~1170-1189)

When WebSocket JSON parsing fails, the error frame sent is `code="QUEUE_FULL"` instead of a parse error code. Clients receive misleading error information.

---

## Medium: Resource Leaks & Error Handling

### 11. Subprocess pipes never consumed

**File:** `orchestrator/container_manager.py` (lines 164-168, 240-244)

`spawn_container()` creates processes with `stdout=PIPE, stderr=PIPE` but callers don't always read them. Open pipes accumulate file descriptors over the orchestrator's lifetime.

### 12. `store_scheduled_message` is not transactional

**File:** `orchestrator/ipc.py` (lines 56-80)

Two separate commits: one for the `messages` INSERT, one inside `queue_message()`. If the second fails, the message is stored but not queued.

### 13. Respawn leaks container on partial failure

**File:** `orchestrator/routes.py` (lines 949-997)

If `spawn_container()` succeeds but the subsequent assignment to `worker.process` fails, the newly spawned container is orphaned. The `except` block doesn't kill it.

### 14. Worker `db.connect()` leaks on extension load failure

**File:** `worker/db.py` (lines 17-28)

If `sqlite_vec.load(_db)` throws, the connection is never closed. Subsequent calls to `connect()` overwrite `_db` without closing the old one.

### 15. Summarization timeout silently returns None

**File:** `worker/memory.py` (lines 86-98)

If session summarization times out, no memory file is written and no event is emitted to the orchestrator. The entire session's content is silently lost from memory.

### 16. Embed retry doesn't catch `json.JSONDecodeError` or `HTTPError`

**File:** `worker/embed.py` (lines 30-56)

Only `URLError`, `OSError`, `ConnectionError` are retried. Transient 5xx responses or malformed JSON from Ollama crash the indexing instead of retrying.

### 17. Hook exceptions break SDK loop

**File:** `worker/agent.py` (lines 179-210)

`emit()` calls inside tool hooks are not wrapped in try/except. If `emit()` fails (DB error), the exception propagates into the SDK's message iteration loop, terminating the query mid-response.

### 18. `index_message` return type mismatch

**File:** `worker/search.py` (lines 17-35)

The function has no return type annotation but actually returns a tuple `(message_id, now)`. Callers depend on this tuple, but the contract is implicit.

### 19. Continuation summary not cleared on query error

**File:** `worker/worker.py` (lines 273-277)

If `run_query()` raises, `_continuation_summary` may not be properly cleared. On the next message, a stale summary could be re-injected into the context.

---

## Low: Minor Issues

### 20. `atomic_write` uses PID for temp filename

**File:** `orchestrator/ipc.py` (line 111), `worker/worker.py` (line 41)

Multiple concurrent async calls to `atomic_write()` on the same path use the same PID suffix, colliding on the temp file. Use `uuid4()` or `os.urandom()` instead.

### 21. Hard-coded Podman path

**File:** `orchestrator/container_manager.py` (line 13)

`PODMAN = "/opt/podman/bin/podman"` -- should be configurable via env var for different deployments.

### 22. Silent failures in `_db_append_token`

**File:** `orchestrator/ipc.py` (lines 131-144)

Returns silently when metadata is not found. No warning logged, making debugging stream gaps difficult.

### 23. Tool output truncated without indicator

**File:** `worker/agent.py` (line 207)

Output silently truncated to 4000 chars with no `truncated: true` flag. The model and UI have no way to know information was lost.

### 24. `fetchall()` on unbounded query

**File:** `worker/memory.py` (lines 60-64)

`summarize_session()` loads all messages for a session into memory at once. Very long sessions could cause memory spikes.

---

## Design Observations

These are systemic patterns rather than individual bugs.

### No `asyncio.Lock` anywhere in the codebase -- FIXED

`_workers_lock` now protects all `_active_workers` access. Task cancellation is awaited before creating replacements.

### Polling loop and scheduler both write `input.json`

If an agentic task and a user message queue flush happen in the same tick for the same session, one overwrites the other (`ipc.py:472` vs `scheduler.py:163`). Currently mitigated because agentic tasks go through the message queue (not direct `input.json` writes), but `scheduled_tasks` still write directly.

### Graceful shutdown clears state before tasks finish -- FIXED

Shutdown now awaits task cancellation before clearing `_active_workers`.
