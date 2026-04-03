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
OUTPUT_PATH = WORKSPACE / "output.jsonl"
POLL_INTERVAL = 0.5

# SDK manages sessions internally via JSONL files in /workspace/sessions/.
# We track the session_id so we can resume on subsequent queries.
_session_id: str | None = None

# Persistent file handle for output — opened once, kept open for the
# lifetime of the worker so the orchestrator can tail it.
_output_fh = None


def _ensure_output_fh():
    global _output_fh
    if _output_fh is None:
        _output_fh = open(OUTPUT_PATH, "a")
    return _output_fh


def emit(event: dict[str, Any]) -> None:
    """Write a JSONL event to /workspace/output.jsonl."""
    line = json.dumps(event) + "\n"
    fh = _ensure_output_fh()
    fh.write(line)
    fh.flush()
    os.fsync(fh.fileno())


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
    sys.stderr.write("worker: starting, connecting to database\n")
    sys.stderr.flush()

    conn = db.connect()
    db.run_migrations(conn)

    # Truncate output file on startup so the orchestrator starts fresh
    OUTPUT_PATH.write_text("")

    sys.stderr.write("worker: ready, polling for input.json\n")
    sys.stderr.flush()

    while True:
        await asyncio.sleep(POLL_INTERVAL)

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
