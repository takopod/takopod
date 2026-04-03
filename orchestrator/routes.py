import asyncio
import json
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from orchestrator.container_manager import spawn_container
from orchestrator.db import get_db
from orchestrator.ipc import get_queue_counts, queue_message, start_polling_loop
from orchestrator.models import ErrorFrame, QueueStatusFrame, UserMessageFrame
from orchestrator.stream_reader import start_stream_reader

router = APIRouter(prefix="/api")

RATE_LIMIT_WINDOW = 60
RATE_LIMIT_MAX = 10
QUEUE_DEPTH_MAX = 50

_rate_limits: dict[str, deque[float]] = defaultdict(deque)


@dataclass
class SessionState:
    container_record_id: str
    process: asyncio.subprocess.Process
    host_dir: Path
    polling_task: asyncio.Task
    stream_task: asyncio.Task


_active_sessions: dict[str, SessionState] = {}


def _check_rate_limit(session_id: str) -> float | None:
    now = time.monotonic()
    dq = _rate_limits[session_id]

    while dq and (now - dq[0]) > RATE_LIMIT_WINDOW:
        dq.popleft()

    if len(dq) >= RATE_LIMIT_MAX:
        retry_after = RATE_LIMIT_WINDOW - (now - dq[0])
        return max(0.0, retry_after)

    dq.append(now)
    return None


async def _create_session() -> str:
    db = await get_db()
    session_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO sessions (id, agent_id) VALUES (?, ?)",
        (session_id, "default"),
    )
    await db.commit()
    return session_id


async def _store_message(session_id: str, frame: UserMessageFrame) -> None:
    db = await get_db()
    await db.execute(
        "INSERT INTO messages (id, session_id, role, content) VALUES (?, ?, ?, ?)",
        (frame.message_id, session_id, "user", frame.content),
    )
    await db.commit()
    await queue_message(session_id, frame.message_id, frame.content)


async def _send_queue_status(ws: WebSocket, session_id: str) -> None:
    counts = await get_queue_counts(session_id)
    status = QueueStatusFrame(**counts)
    await ws.send_text(status.model_dump_json())


async def _ensure_worker(session_id: str, ws: WebSocket) -> None:
    if session_id in _active_sessions:
        return

    record_id, process, host_dir = await spawn_container(session_id)
    polling_task = start_polling_loop(session_id, host_dir, ws)
    stream_task = start_stream_reader(process, ws, session_id)

    _active_sessions[session_id] = SessionState(
        container_record_id=record_id,
        process=process,
        host_dir=host_dir,
        polling_task=polling_task,
        stream_task=stream_task,
    )


def _cleanup_session(session_id: str) -> None:
    state = _active_sessions.pop(session_id, None)
    if state:
        state.polling_task.cancel()
        state.stream_task.cancel()
    _rate_limits.pop(session_id, None)


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    session_id = await _create_session()

    try:
        while True:
            raw = await ws.receive_text()

            try:
                data = json.loads(raw)
                frame = UserMessageFrame.model_validate(data)
            except (json.JSONDecodeError, ValidationError):
                error = ErrorFrame(code="QUEUE_FULL")
                await ws.send_text(error.model_dump_json())
                continue

            retry_after = _check_rate_limit(session_id)
            if retry_after is not None:
                error = ErrorFrame(
                    code="RATE_LIMITED",
                    retry_after_seconds=round(retry_after, 1),
                )
                await ws.send_text(error.model_dump_json())
                continue

            counts = await get_queue_counts(session_id)
            if counts["queued"] >= QUEUE_DEPTH_MAX:
                error = ErrorFrame(code="QUEUE_FULL")
                await ws.send_text(error.model_dump_json())
                continue

            await _store_message(session_id, frame)
            await _send_queue_status(ws, session_id)
            await _ensure_worker(session_id, ws)

    except WebSocketDisconnect:
        _cleanup_session(session_id)
