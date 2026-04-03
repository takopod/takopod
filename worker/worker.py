"""Worker: polls /workspace/input.json, runs Claude queries via Vertex AI."""

import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from worker import db
from worker.agent import run_query

WORKSPACE = Path("/workspace")
INPUT_PATH = WORKSPACE / "input.json"
SESSIONS_DIR = WORKSPACE / "sessions"
CURRENT_SESSION_FILE = SESSIONS_DIR / "current_session_id"
POLL_INTERVAL = 0.5


def emit(event: dict[str, Any]) -> None:
    """Write a JSONL event to stdout."""
    print(json.dumps(event), flush=True)


class SessionManager:
    """Manages conversation history and session persistence."""

    def __init__(self) -> None:
        SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
        self.session_id: str = self._load_or_create_session_id()
        self.messages: list[dict[str, Any]] = self._load_session()

    def _load_or_create_session_id(self) -> str:
        if CURRENT_SESSION_FILE.is_file():
            return CURRENT_SESSION_FILE.read_text().strip()
        session_id = str(uuid.uuid4())
        CURRENT_SESSION_FILE.write_text(session_id)
        return session_id

    def _session_file(self) -> Path:
        return SESSIONS_DIR / f"{self.session_id}.jsonl"

    def _load_session(self) -> list[dict[str, Any]]:
        sf = self._session_file()
        if not sf.is_file():
            return []
        messages = []
        for line in sf.read_text().strip().splitlines():
            if line:
                messages.append(json.loads(line))
        return messages

    def save(self) -> None:
        sf = self._session_file()
        with open(sf, "w") as f:
            for msg in self.messages:
                f.write(json.dumps(msg) + "\n")

    def clear(self) -> None:
        self.session_id = str(uuid.uuid4())
        CURRENT_SESSION_FILE.write_text(self.session_id)
        self.messages = []


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


def process_message(
    msg: dict[str, Any],
    session: SessionManager,
    conn,
) -> None:
    msg_type = msg.get("type")

    if msg_type == "system_command":
        command = msg.get("command")
        if command == "clear_context":
            session.clear()
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
    emit({"type": "status", "status": "thinking", "message_id": message_id})

    try:
        run_query(message_id, content, session.messages, emit)
        session.save()
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


def main() -> None:
    sys.stderr.write("worker: starting, connecting to database\n")
    sys.stderr.flush()

    conn = db.connect()
    db.run_migrations(conn)

    session = SessionManager()

    sys.stderr.write(
        f"worker: ready, session={session.session_id}, polling for input.json\n"
    )
    sys.stderr.flush()

    while True:
        time.sleep(POLL_INTERVAL)

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
            process_message(msg, session, conn)


if __name__ == "__main__":
    main()
