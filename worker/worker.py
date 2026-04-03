"""Worker: polls /workspace/input.json, runs Claude queries via Agent SDK."""

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

from worker import db
from worker.agent import run_query

WORKSPACE = Path("/workspace")
INPUT_PATH = WORKSPACE / "input.json"
RESPONSE_PATH = WORKSPACE / "response.json"
POLL_INTERVAL = 0.5

# SDK manages sessions internally via JSONL files in /workspace/sessions/.
# We track the session_id so we can resume on subsequent queries.
_session_id: str | None = None

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


async def process_message(msg: dict[str, Any], conn) -> None:
    global _session_id
    msg_type = msg.get("type")

    if msg_type == "system_command":
        command = msg.get("command")
        if command == "clear_context":
            _session_id = None  # Next query starts a fresh SDK session
            emit({"type": "status", "status": "context_cleared", "message_id": ""})
        elif command == "shutdown":
            sys.stderr.write("worker: received shutdown command, exiting\n")
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
    sys.stderr.write(f"worker: query message_id={message_id} content={content!r}\n")
    sys.stderr.flush()
    emit({"type": "status", "status": "thinking", "message_id": message_id})

    try:
        new_session_id, _usage = await run_query(
            message_id, content, _session_id, emit,
        )
        _session_id = new_session_id
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
