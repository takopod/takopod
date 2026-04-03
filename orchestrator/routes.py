import asyncio
import json
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from orchestrator.container_manager import (
    create_agent_workspace,
    spawn_container,
)
from orchestrator.db import get_db
from orchestrator.ipc import get_queue_counts, queue_message, start_polling_loop
from orchestrator.models import (
    AgentDetailResponse,
    AgentResponse,
    CreateAgentRequest,
    ErrorFrame,
    QueueStatusFrame,
    UpdateAgentRequest,
    UserMessageFrame,
)
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


# --- Agent CRUD ---


@router.post("/agents")
async def create_agent(req: CreateAgentRequest) -> AgentResponse:
    db = await get_db()
    agent_id = str(uuid.uuid4())
    host_dir = create_agent_workspace(agent_id, req.agent_type)

    await db.execute(
        "INSERT INTO agents (id, name, agent_type, host_dir) VALUES (?, ?, ?, ?)",
        (agent_id, req.name, req.agent_type, str(host_dir)),
    )
    await db.commit()

    async with db.execute(
        "SELECT id, name, agent_type, status, created_at FROM agents WHERE id = ?",
        (agent_id,),
    ) as cur:
        row = await cur.fetchone()

    return AgentResponse(
        id=row[0], name=row[1], agent_type=row[2], status=row[3], created_at=row[4]
    )


@router.get("/agents")
async def list_agents() -> list[AgentResponse]:
    db = await get_db()
    async with db.execute(
        "SELECT id, name, agent_type, status, created_at FROM agents "
        "WHERE status = 'active' ORDER BY created_at"
    ) as cur:
        rows = await cur.fetchall()
    return [
        AgentResponse(
            id=r[0], name=r[1], agent_type=r[2], status=r[3], created_at=r[4]
        )
        for r in rows
    ]


@router.get("/agents/{agent_id}")
async def get_agent(agent_id: str) -> AgentDetailResponse:
    db = await get_db()
    async with db.execute(
        "SELECT id, name, agent_type, status, created_at, host_dir FROM agents "
        "WHERE id = ?",
        (agent_id,),
    ) as cur:
        row = await cur.fetchone()
    if not row:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Agent not found")

    host_dir = Path(row[5])
    claude_md = (host_dir / "CLAUDE.md").read_text() if (host_dir / "CLAUDE.md").is_file() else ""
    soul_md = (host_dir / "SOUL.md").read_text() if (host_dir / "SOUL.md").is_file() else ""
    memory_md = (host_dir / "MEMORY.md").read_text() if (host_dir / "MEMORY.md").is_file() else ""

    return AgentDetailResponse(
        id=row[0], name=row[1], agent_type=row[2], status=row[3],
        created_at=row[4], claude_md=claude_md, soul_md=soul_md, memory_md=memory_md,
    )


@router.put("/agents/{agent_id}")
async def update_agent(agent_id: str, req: UpdateAgentRequest) -> AgentDetailResponse:
    db = await get_db()
    async with db.execute(
        "SELECT host_dir FROM agents WHERE id = ?", (agent_id,)
    ) as cur:
        row = await cur.fetchone()
    if not row:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Agent not found")

    host_dir = Path(row[0])
    updates: list[tuple[str, str]] = []
    if req.claude_md is not None:
        (host_dir / "CLAUDE.md").write_text(req.claude_md)
        updates.append(("claude_md", req.claude_md))
    if req.soul_md is not None:
        (host_dir / "SOUL.md").write_text(req.soul_md)
        updates.append(("soul_md", req.soul_md))
    if req.memory_md is not None:
        (host_dir / "MEMORY.md").write_text(req.memory_md)
        updates.append(("memory_md", req.memory_md))

    if updates:
        set_clause = ", ".join(f"{col} = ?" for col, _ in updates)
        values = [v for _, v in updates]
        await db.execute(
            f"UPDATE agents SET {set_clause} WHERE id = ?",
            (*values, agent_id),
        )
        await db.commit()

    return await get_agent(agent_id)


# --- WebSocket ---


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


async def _create_session(agent_id: str) -> str:
    db = await get_db()
    session_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO sessions (id, agent_id) VALUES (?, ?)",
        (session_id, agent_id),
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


async def _ensure_worker(
    agent_id: str, session_id: str, ws: WebSocket
) -> None:
    if session_id in _active_sessions:
        return

    record_id, process, host_dir = await spawn_container(agent_id, session_id)
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

    agent_id = ws.query_params.get("agent_id")
    if not agent_id:
        await ws.send_text(
            ErrorFrame(code="QUEUE_FULL").model_dump_json()
        )
        await ws.close()
        return

    db = await get_db()
    async with db.execute(
        "SELECT id FROM agents WHERE id = ? AND status = 'active'", (agent_id,)
    ) as cur:
        if not await cur.fetchone():
            await ws.send_text(
                ErrorFrame(code="QUEUE_FULL").model_dump_json()
            )
            await ws.close()
            return

    session_id = await _create_session(agent_id)

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
            await _ensure_worker(agent_id, session_id, ws)

    except WebSocketDisconnect:
        _cleanup_session(session_id)
