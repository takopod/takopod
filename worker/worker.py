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
RESPONSE_PATH = WORKSPACE / "response.json"
POLL_INTERVAL = 0.5

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

# Module-level DB connection, set in main().
_conn = None


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
    """Flush pending worker_responses rows to response.json if absent."""
    if RESPONSE_PATH.exists():
        return
    rows = _conn.execute(
        "SELECT id, event FROM worker_responses "
        "WHERE status = 'pending' ORDER BY id",
    ).fetchall()
    if not rows:
        return
    events = [json.loads(row[1]) for row in rows]
    atomic_write(RESPONSE_PATH, json.dumps(events).encode())
    ids = [row[0] for row in rows]
    placeholders = ",".join("?" * len(ids))
    _conn.execute(
        f"UPDATE worker_responses SET status = 'sent' WHERE id IN ({placeholders})",
        ids,
    )
    _conn.commit()


def emit(event: dict[str, Any]) -> None:
    """Insert event into worker_responses and attempt to flush."""
    _conn.execute(
        "INSERT INTO worker_responses (message_id, event) VALUES (?, ?)",
        (event.get("message_id", ""), json.dumps(event)),
    )
    _conn.commit()
    flush_responses()


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


async def _split_session(conn) -> None:
    """Split the SDK session due to context overflow.

    Summarizes the current session, writes a memory file, stores the summary
    for the next query, and resets the SDK session.  The orchestrator session
    and WebSocket connection are unaffected.
    """
    global _session_id, _continuation_summary

    try:
        from worker.memory import (
            compact_memory_files,
            summarize_session,
            write_memory_file,
        )

        # Summarize the session (used both for memory and continuation seed)
        summary = await summarize_session(conn, _orch_session_id)
        if summary:
            # Write to daily memory file
            sdk_path = (
                f"sessions/{_session_id}.jsonl"
                if _session_id
                else f"sessions/unknown-{(_orch_session_id or 'none')[:8]}"
            )
            _path, needs_compaction = write_memory_file(conn, summary, sdk_path)
            _continuation_summary = summary

            if needs_compaction:
                today = time.strftime("%Y-%m-%d", time.gmtime())
                try:
                    await compact_memory_files(conn, today)
                except Exception as e:
                    sys.stderr.write(f"worker: compaction failed: {e}\n")
                    sys.stderr.flush()

        # Reset SDK session — next query creates a fresh one
        _session_id = None
        sys.stderr.write("worker: session split complete\n")
        sys.stderr.flush()

    except Exception as e:
        sys.stderr.write(f"worker: session split failed: {e}\n")
        sys.stderr.flush()


async def process_message(msg: dict[str, Any], conn) -> None:
    global _session_id, _orch_session_id, _continuation_summary
    msg_type = msg.get("type")

    if msg_type == "system_command":
        command = msg.get("command")
        if command == "clear_context":
            # Summarize the current session before clearing
            try:
                from worker.memory import run_session_end
                await run_session_end(conn, _orch_session_id, _session_id)
            except Exception as e:
                sys.stderr.write(f"worker: session-end summary failed: {e}\n")
                sys.stderr.flush()
            _session_id = None  # Next query starts a fresh SDK session
            emit({"type": "status", "status": "context_cleared", "message_id": ""})
        elif command == "shutdown":
            sys.stderr.write("worker: received shutdown command, summarizing session\n")
            sys.stderr.flush()
            try:
                from worker.memory import run_session_end
                await run_session_end(conn, _orch_session_id, _session_id)
            except Exception as e:
                sys.stderr.write(f"worker: session-end summary failed: {e}\n")
                sys.stderr.flush()
            emit({"type": "status", "status": "done", "message_id": ""})
            flush_responses()
            sys.exit(0)
        return

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

    content = msg.get("content", "")
    session_id_for_index = msg.get("session_id", "")
    _orch_session_id = session_id_for_index or _orch_session_id
    sys.stderr.write(f"worker: query message_id={message_id} content={content!r}\n")
    sys.stderr.flush()
    emit({"type": "status", "status": "thinking", "message_id": message_id})

    # Retrieve relevant past context via hybrid search
    retrieved_context = None
    try:
        from worker.search import search_hybrid, format_context
        results = await search_hybrid(conn, content)
        retrieved_context = format_context(results)
        if retrieved_context:
            sys.stderr.write(
                f"worker: retrieved {len(results)} search results for context\n"
            )
            sys.stderr.flush()
    except Exception as e:
        sys.stderr.write(f"worker: search failed, proceeding without context: {e}\n")
        sys.stderr.flush()

    # Load memory context (MEMORY.md + daily memory files)
    memory_context = None
    try:
        from worker.memory import load_memory_context
        memory_context = load_memory_context(conn)
        if memory_context:
            sys.stderr.write(
                f"worker: loaded memory context ({len(memory_context)} chars)\n"
            )
            sys.stderr.flush()
    except Exception as e:
        sys.stderr.write(f"worker: memory loading failed: {e}\n")
        sys.stderr.flush()

    response_text = ""
    try:
        new_session_id, _usage, response_text = await run_query(
            message_id, content, _session_id, emit,
            retrieved_context=retrieved_context,
            memory_context=memory_context,
            continuation_summary=_continuation_summary,
        )
        _session_id = new_session_id
        # Clear continuation summary after it has been consumed
        _continuation_summary = None

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
    except Exception as e:
        sys.stderr.write(f"worker: query error: {e}\n")
        sys.stderr.flush()
        emit({
            "type": "system_error",
            "error": str(e),
            "fatal": False,
            "message_id": message_id,
        })

    _mark_processed(conn, message_id)
    emit({"type": "status", "status": "done", "message_id": message_id})

    # Index the conversation turn for future retrieval
    try:
        from worker.search import index_message, index_vector
        _, user_ts = index_message(conn, message_id, session_id_for_index, "user", content)
        await index_vector(conn, message_id, session_id_for_index, "user", content, user_ts)
        if response_text:
            resp_id = message_id + "-response"
            _, resp_ts = index_message(conn, resp_id, session_id_for_index, "assistant", response_text)
            await index_vector(conn, resp_id, session_id_for_index, "assistant", response_text, resp_ts)
    except Exception as e:
        sys.stderr.write(f"worker: indexing failed: {e}\n")
        sys.stderr.flush()


async def main() -> None:
    global _conn

    sys.stderr.write("worker: starting, connecting to database\n")
    sys.stderr.flush()

    _conn = db.connect()
    conn = _conn
    db.run_migrations(conn)

    # Clean up stale state from a previous run
    if RESPONSE_PATH.exists():
        os.remove(RESPONSE_PATH)
    conn.execute("UPDATE worker_responses SET status = 'sent' WHERE status = 'pending'")
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

    sys.stderr.write("worker: ready, polling for input.json\n")
    sys.stderr.flush()

    while True:
        await asyncio.sleep(POLL_INTERVAL)

        # Flush any pending responses each iteration (catches events
        # that couldn't be flushed because response.json still existed)
        flush_responses()

        if not INPUT_PATH.exists():
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
