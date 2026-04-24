"""Worker: polls /workspace/input.json, runs Claude queries via Agent SDK."""

import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from worker import db
from worker.agent import run_query

WORKSPACE = Path("/workspace")
INPUT_PATH = WORKSPACE / "input.json"
OUTPUT_PATH = WORKSPACE / "output.json"
CANCEL_PATH = WORKSPACE / "cancel.json"
SESSION_HISTORY_PATH = WORKSPACE / "session_history.json"
SETTINGS_PATH = WORKSPACE / ".settings.json"
POLL_INTERVAL = 0.5
DEFAULT_WINDOW_SIZE = 20

# Context overflow: split the SDK session when input tokens exceed 80% of the
# model's context window.  The orchestrator session stays unchanged.
CONTEXT_WINDOW = 200_000  # tokens (Claude model context window)
CONTEXT_THRESHOLD = 0.80  # trigger split at this fraction

# SDK manages sessions internally via JSONL files in /workspace/sessions/.
# We track the session_id so we can resume on subsequent queries.
_session_id: str | None = None

# Orchestrator session ID, set from user_message payloads.
# System commands (shutdown, clear_context) don't carry session_id,
# so we remember the last one seen.
_orch_session_id: str | None = None

# After a context-overflow split, the summary is stored here and injected
# into the next query's system prompt so the new SDK session has continuity.
_continuation_summary: str | None = None

# In-memory transcript of the current session's conversation.
# Accumulates (role, content) tuples for summarization at session end
# or context overflow.  Cleared on split/end.
_session_transcript: list[tuple[str, str]] = []

# In-memory buffer for events waiting to be flushed to output.json.
_pending_events: list[dict[str, Any]] = []

# Agentic task ID for the currently executing scheduled message.
# Set when processing a user_message with an agentic_task_id field,
# read by the signal_activity tool to auto-detect the task.
_current_agentic_task_id: str | None = None

# Module-level DB connection, set in main().
_conn = None


def _cleanup_attachments(attachments: list[str]) -> None:
    """Delete uploaded attachment files and their parent upload directory."""
    dirs_to_remove: set[Path] = set()
    for rel_path in attachments:
        full_path = WORKSPACE / rel_path
        try:
            full_path.unlink(missing_ok=True)
            dirs_to_remove.add(full_path.parent)
        except OSError:
            pass
    # Remove empty upload-id directories (e.g. uploads/abc12345/)
    for d in dirs_to_remove:
        try:
            if d.is_dir() and not any(d.iterdir()):
                d.rmdir()
        except OSError:
            pass
    sys.stderr.write(f"worker: cleaned up {len(attachments)} attachment(s)\n")
    sys.stderr.flush()


def atomic_write(path: Path, data: bytes) -> None:
    """Write data to path atomically via temp file + rename."""
    temp_path = path.parent / f"{path.name}.tmp.{os.getpid()}"
    try:
        fd = os.open(str(temp_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
        try:
            os.write(fd, data)
            os.fsync(fd)
        finally:
            os.close(fd)
        os.rename(str(temp_path), str(path))
    except BaseException:
        try:
            os.unlink(str(temp_path))
        except FileNotFoundError:
            pass
        raise


def flush_responses() -> None:
    """Flush pending events to output.json if absent."""
    if OUTPUT_PATH.exists() or not _pending_events:
        return
    atomic_write(OUTPUT_PATH, json.dumps(_pending_events).encode())
    _pending_events.clear()


def emit(event: dict[str, Any]) -> None:
    """Append event to the pending list and attempt to flush."""
    _pending_events.append(event)
    flush_responses()


def drain_pending(max_wait: float = 10.0) -> None:
    """Block until all pending events are flushed to output.json.

    Waits for the orchestrator to consume any existing output.json, then
    flushes remaining pending events.  Gives up after *max_wait* seconds.
    """
    deadline = time.monotonic() + max_wait
    while time.monotonic() < deadline:
        if not _pending_events:
            return
        if not OUTPUT_PATH.exists():
            flush_responses()
        else:
            time.sleep(0.1)


async def _cancel_monitor(task: asyncio.Task) -> None:
    """Poll for cancel.json and cancel the query task when found."""
    while not task.done():
        await asyncio.sleep(0.5)
        if CANCEL_PATH.exists():
            CANCEL_PATH.unlink(missing_ok=True)
            task.cancel()
            return


def _is_processed(conn, message_id: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM processed_messages WHERE message_id = ?",
        (message_id,),
    ).fetchone()
    return row is not None


def _mark_processed(conn, message_id: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO processed_messages (message_id) VALUES (?)",
        (message_id,),
    )
    conn.commit()


def _get_window_size() -> int:
    if SETTINGS_PATH.is_file():
        try:
            config = json.loads(SETTINGS_PATH.read_text())
            return int(config.get("session_history_window_size", DEFAULT_WINDOW_SIZE))
        except (json.JSONDecodeError, ValueError):
            pass
    return DEFAULT_WINDOW_SIZE


def _persist_session_history() -> None:
    window = _get_window_size()
    entries = _session_transcript[-window:]
    data = [{"role": role, "content": content} for role, content in entries]
    atomic_write(SESSION_HISTORY_PATH, json.dumps(data).encode())


def _load_session_history() -> tuple[list[tuple[str, str]], str | None]:
    """Load session history, returning raw entries and formatted summary."""
    if not SESSION_HISTORY_PATH.is_file():
        return [], None
    try:
        raw = json.loads(SESSION_HISTORY_PATH.read_text())
        if not raw:
            return [], None
        entries = []
        lines = []
        for entry in raw:
            role = entry.get("role", "unknown")
            content = entry.get("content", "")
            entries.append((role, content))
            lines.append(f"[{role}]: {content}")
        return entries, "\n\n".join(lines)
    except (json.JSONDecodeError, OSError):
        return [], None


async def _split_session(conn) -> None:
    """Split the SDK session due to context overflow.

    Summarizes the current session, writes a memory file, stores the summary
    for the next query, and resets the SDK session.  The orchestrator session
    and WebSocket connection are unaffected.
    """
    global _session_id, _continuation_summary, _session_transcript

    try:
        from worker.memory import summarize_session, write_memory_file
        from worker.search import index_memory_vectors

        # Summarize from in-memory transcript
        summary = await summarize_session(_session_transcript)
        if summary:
            session_ref = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
            _path, needs_compaction = write_memory_file(conn, summary, session_ref)
            _continuation_summary = summary

            # Async vector indexing
            if _path:
                file_content = (WORKSPACE / _path).read_text()
                await index_memory_vectors(conn, _path, file_content)

            if needs_compaction:
                today = time.strftime("%Y-%m-%d", time.gmtime())
                emit({"type": "schedule_compaction", "date": today, "message_id": ""})
                sys.stderr.write(f"worker: scheduled compaction for {today}\n")
                sys.stderr.flush()

        # Reset SDK session; keep last N transcript entries for session history
        _session_id = None
        window = _get_window_size()
        _session_transcript = _session_transcript[-window:]
        sys.stderr.write("worker: session split complete\n")
        sys.stderr.flush()

    except Exception as e:
        sys.stderr.write(f"worker: session split failed: {e}\n")
        sys.stderr.flush()


async def _handle_scheduled_task(conn, msg: dict[str, Any]) -> dict:
    """Execute a scheduled task inside an ephemeral container."""
    task_type = msg.get("task_type", "")
    payload = msg.get("payload", {})
    task_id = msg.get("task_id", "")

    sys.stderr.write(f"worker: handling scheduled task {task_id[:8]} type={task_type}\n")
    sys.stderr.flush()

    if task_type == "memory_compaction":
        from worker.memory import compact_memory_files
        date = payload.get("date")
        if not date:
            return {"error": "missing date in payload"}
        result_path = await compact_memory_files(conn, date)
        return {"compacted_path": result_path}

    return {"error": f"unknown task type: {task_type}"}


async def process_message(msg: dict[str, Any], conn) -> None:
    global _session_id, _orch_session_id, _continuation_summary, _session_transcript, _current_agentic_task_id
    msg_type = msg.get("type")

    if msg_type == "system_command":
        command = msg.get("command")
        if command == "clear_context":
            # Summarize the current session before clearing
            try:
                from worker.memory import run_session_end
                compaction_date = await run_session_end(
                    conn, _session_transcript,
                )
                if compaction_date:
                    emit({"type": "schedule_compaction", "date": compaction_date, "message_id": ""})
            except Exception as e:
                sys.stderr.write(f"worker: session-end summary failed: {e}\n")
                sys.stderr.flush()
            _session_id = None  # Next query starts a fresh SDK session
            _continuation_summary = None
            _session_transcript = []
            if SESSION_HISTORY_PATH.exists():
                os.remove(SESSION_HISTORY_PATH)
            emit({"type": "status", "status": "context_cleared", "message_id": ""})
        elif command == "shutdown":
            sys.stderr.write("worker: received shutdown command, summarizing session\n")
            sys.stderr.flush()
            try:
                from worker.memory import run_session_end
                compaction_date = await run_session_end(
                    conn, _session_transcript,
                )
                if compaction_date:
                    emit({"type": "schedule_compaction", "date": compaction_date, "message_id": ""})
            except Exception as e:
                sys.stderr.write(f"worker: session-end summary failed: {e}\n")
                sys.stderr.flush()
            _persist_session_history()
            emit({"type": "status", "status": "done", "message_id": ""})
            flush_responses()
            sys.exit(0)
        return

    if msg_type == "scheduled_task":
        result = await _handle_scheduled_task(conn, msg)
        status = "error" if "error" in result else "completed"
        emit({
            "type": "task_result",
            "task_id": msg.get("task_id", ""),
            "status": status,
            "result": result,
            "message_id": "",
        })
        flush_responses()
        sys.exit(0)

    if msg_type != "user_message":
        sys.stderr.write(f"worker: unknown message type: {msg_type}\n")
        sys.stderr.flush()
        return

    message_id = msg.get("message_id", "")
    if not message_id:
        return

    if _is_processed(conn, message_id):
        sys.stderr.write(f"worker: skipping duplicate message {message_id}\n")
        sys.stderr.flush()
        return

    _current_agentic_task_id = msg.get("agentic_task_id")

    content = msg.get("content", "")
    attachments: list[str] = msg.get("attachments", [])
    session_id_from_msg = msg.get("session_id", "")
    _orch_session_id = session_id_from_msg or _orch_session_id
    sys.stderr.write(f"worker: query message_id={message_id} content={content!r}\n")
    if attachments:
        sys.stderr.write(f"worker: attachments={attachments}\n")
    sys.stderr.flush()
    emit({"type": "status", "status": "thinking", "message_id": message_id})

    # Prepend attachment references so the SDK's Read tool can access them
    if attachments:
        file_lines = "\n".join(
            f"- /workspace/{path}" for path in attachments
        )
        content = (
            f"The user attached the following files. Use the Read tool to view them:\n"
            f"{file_lines}\n\n{content}"
        )

    # Load context budget config
    from worker.context_budget import get_config
    config = get_config()

    # Retrieve relevant past context via hybrid search (memory summaries)
    retrieved_context = None
    try:
        from worker.search import search_hybrid, format_context, rewrite_query, MIN_QUERY_LENGTH
        if len(content.strip()) >= MIN_QUERY_LENGTH:
            search_query = rewrite_query(content)
            results = await search_hybrid(conn, search_query)
            retrieved_context = format_context(results, max_tokens=config.search_tokens)
            if retrieved_context:
                sys.stderr.write(
                    f"worker: retrieved {len(results)} search results for context\n"
                )
                sys.stderr.flush()
        else:
            sys.stderr.write(
                f"worker: skipping search (query too short: {len(content.strip())} chars)\n"
            )
            sys.stderr.flush()
    except Exception as e:
        sys.stderr.write(f"worker: search failed, proceeding without context: {e}\n")
        sys.stderr.flush()

    # Load memory context (MEMORY.md + daily memory files)
    memory_context = None
    try:
        from worker.memory import load_memory_context
        memory_context = load_memory_context()
        if memory_context:
            sys.stderr.write(
                f"worker: loaded memory context ({len(memory_context)} chars)\n"
            )
            sys.stderr.flush()
    except Exception as e:
        sys.stderr.write(f"worker: memory loading failed: {e}\n")
        sys.stderr.flush()

    # Extract structured facts from cached memory data (P2)
    facts_context = None
    try:
        from worker.memory import get_facts_context
        facts_context = get_facts_context(conn)
        if facts_context:
            sys.stderr.write(
                f"worker: facts context ({len(facts_context)} chars)\n"
            )
            sys.stderr.flush()
    except Exception as e:
        sys.stderr.write(f"worker: fact extraction failed: {e}\n")
        sys.stderr.flush()

    response_text = ""
    partial_text_ref = [""]
    query_task = asyncio.create_task(run_query(
        message_id, content, _session_id, emit,
        conn=conn,
        retrieved_context=retrieved_context,
        memory_context=memory_context,
        continuation_summary=_continuation_summary,
        facts_context=facts_context,
        msg_payload=msg,
        partial_text_ref=partial_text_ref,
    ))
    monitor_task = asyncio.create_task(_cancel_monitor(query_task))
    try:
        new_session_id, _usage, response_text = await query_task
        _session_id = new_session_id
        # Clear continuation summary after it has been consumed
        _continuation_summary = None

        # Accumulate transcript before potential split (which clears it)
        _session_transcript.append(("user", content))
        if response_text:
            _session_transcript.append(("assistant", response_text))
        _persist_session_history()

        # Context overflow check: if input tokens exceed the threshold,
        # split the SDK session.  The orchestrator session is unaffected.
        input_tokens = _usage.get("input_tokens", 0)
        if input_tokens > CONTEXT_WINDOW * CONTEXT_THRESHOLD:
            sys.stderr.write(
                f"worker: context overflow detected "
                f"({input_tokens}/{CONTEXT_WINDOW} tokens, "
                f"threshold {CONTEXT_THRESHOLD:.0%}), splitting session\n"
            )
            sys.stderr.flush()
            await _split_session(conn)
    except asyncio.CancelledError:
        response_text = partial_text_ref[0]
        stopped_text = (
            response_text + "\n\n[Generation stopped by user]"
            if response_text
            else "[Generation stopped by user]"
        )
        sys.stderr.write("worker: query cancelled by user\n")
        sys.stderr.flush()
        emit({
            "type": "complete",
            "content": stopped_text,
            "message_id": message_id,
            "usage": {},
        })
        drain_pending()
        _session_id = None
        _session_transcript.append(("user", content))
        _session_transcript.append(("assistant", stopped_text))
        _persist_session_history()
    except Exception as e:
        sys.stderr.write(f"worker: query error: {e}\n")
        sys.stderr.flush()
        emit({
            "type": "system_error",
            "error": str(e),
            "fatal": False,
            "message_id": message_id,
        })
    finally:
        monitor_task.cancel()

    # Clean up uploaded attachment files — the SDK has already read them
    if attachments:
        _cleanup_attachments(attachments)

    _mark_processed(conn, message_id)
    emit({"type": "status", "status": "done", "message_id": message_id})


async def main() -> None:
    global _conn, _continuation_summary

    logs_dir = WORKSPACE / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    # Prune old log files, keep last 9 (+ the new one = 10)
    old_logs = sorted(logs_dir.glob("worker-*.log"))
    for stale in old_logs[:-9]:
        stale.unlink(missing_ok=True)

    timestamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    log_file = open(logs_dir / f"worker-{timestamp}.log", "w")
    sys.stderr = log_file

    sys.stderr.write("worker: starting, connecting to database\n")
    sys.stderr.flush()

    _conn = db.connect()
    conn = _conn
    db.run_migrations(conn)

    # Clean up stale state from a previous run
    if OUTPUT_PATH.exists():
        os.remove(OUTPUT_PATH)
    CANCEL_PATH.unlink(missing_ok=True)
    conn.execute("DELETE FROM processed_messages")
    conn.commit()

    # Ollama smoke test — non-fatal, workers function without embeddings
    try:
        from worker.embed import embed
        vec = await embed("smoke test")
        sys.stderr.write(
            f"worker: Ollama connectivity OK — embedding dim={len(vec)}\n"
        )
        sys.stderr.flush()
    except Exception as e:
        sys.stderr.write(
            f"worker: Ollama not reachable: {e} — embeddings disabled\n"
        )
        sys.stderr.flush()

    # One-time migration: import markdown-embedded facts into DB (P7)
    try:
        from worker.memory import migrate_markdown_facts_to_db
        migrate_markdown_facts_to_db(conn)
    except Exception as e:
        sys.stderr.write(f"worker: markdown facts migration failed: {e}\n")
        sys.stderr.flush()

    # Backfill memory search index if empty but memory files exist on disk
    try:
        fts_count = conn.execute("SELECT COUNT(*) FROM memory_fts").fetchone()[0]
        if fts_count == 0:
            memory_dir = WORKSPACE / "memory"
            if memory_dir.is_dir():
                from worker.search import index_memory_file, index_memory_vectors
                md_files = sorted(memory_dir.glob("*.md"))
                if md_files:
                    sys.stderr.write(
                        f"worker: backfilling memory index ({len(md_files)} files)\n"
                    )
                    sys.stderr.flush()
                    for md_file in md_files:
                        rel_path = f"memory/{md_file.name}"
                        file_content = md_file.read_text()
                        index_memory_file(conn, rel_path, file_content)
                        await index_memory_vectors(conn, rel_path, file_content)
                    sys.stderr.write("worker: memory index backfill complete\n")
                    sys.stderr.flush()
    except Exception as e:
        sys.stderr.write(f"worker: memory index backfill failed: {e}\n")
        sys.stderr.flush()

    # Prune old index entries based on retention policy (P3)
    try:
        from worker.search import prune_old_index_entries
        from worker.context_budget import get_config as _get_config
        _cfg = _get_config()
        pruned = prune_old_index_entries(conn, _cfg.retention_days)
        if pruned > 0:
            sys.stderr.write(f"worker: pruned {pruned} old index entries\n")
            sys.stderr.flush()
    except Exception as e:
        sys.stderr.write(f"worker: index pruning failed: {e}\n")
        sys.stderr.flush()

    # Restore conversation context from previous session if available.
    # Pre-populate _session_transcript so old entries survive the next persist.
    history_entries, history_summary = _load_session_history()
    if history_entries:
        _session_transcript = history_entries
        _continuation_summary = history_summary
        sys.stderr.write(
            f"worker: loaded {len(history_entries)} session history entries "
            "as continuation context\n"
        )
        sys.stderr.flush()

    sys.stderr.write("worker: ready, polling for input.json\n")
    sys.stderr.flush()

    while True:
        await asyncio.sleep(POLL_INTERVAL)

        # Flush any pending responses each iteration (catches events
        # that couldn't be flushed because output.json still existed)
        flush_responses()

        if not INPUT_PATH.exists():
            CANCEL_PATH.unlink(missing_ok=True)
            continue

        try:
            with open(INPUT_PATH) as f:
                data = json.load(f)
            os.remove(INPUT_PATH)
        except (json.JSONDecodeError, OSError) as e:
            sys.stderr.write(f"worker: error reading input.json: {e}\n")
            sys.stderr.flush()
            continue

        messages = data if isinstance(data, list) else [data]
        for msg in messages:
            await process_message(msg, conn)


if __name__ == "__main__":
    asyncio.run(main())
