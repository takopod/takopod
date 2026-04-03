import asyncio
import json
import logging
import os
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from orchestrator.container_manager import (
    create_agent_workspace,
    kill_container,
    spawn_container,
)
from orchestrator.db import get_db
from orchestrator.ipc import (
    get_queue_counts,
    queue_message,
    queue_system_command,
    start_polling_loop,
)
from orchestrator.models import (
    AgentDetailResponse,
    AgentResponse,
    ContainerResponse,
    CreateAgentRequest,
    ErrorFrame,
    FileEntry,
    QueueStatusFrame,
    SystemCommandFrame,
    UpdateAgentRequest,
    UserMessageFrame,
)
from orchestrator.stream_reader import StreamReader

router = APIRouter(prefix="/api")

RATE_LIMIT_WINDOW = 60
RATE_LIMIT_MAX = 10
QUEUE_DEPTH_MAX = 50
IDLE_TIMEOUT_SECONDS = int(os.environ.get("IDLE_TIMEOUT_SECONDS", "300"))  # 5 minutes

_rate_limits: dict[str, deque[float]] = defaultdict(deque)


logger = logging.getLogger(__name__)


@dataclass
class WorkerState:
    """Tracks a running worker container for an agent."""
    container_record_id: str
    process: asyncio.subprocess.Process
    host_dir: Path
    session_id: str
    stream_reader: StreamReader
    polling_task: asyncio.Task | None = None


# Keyed by agent_id — one worker per agent
_active_workers: dict[str, WorkerState] = {}


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


@router.delete("/agents/{agent_id}")
async def delete_agent(agent_id: str):
    """Archive an agent and kill its running container if any."""
    db = await get_db()
    async with db.execute(
        "SELECT id FROM agents WHERE id = ? AND status = 'active'",
        (agent_id,),
    ) as cur:
        row = await cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Agent not found")

    # Kill running container
    worker = _active_workers.pop(agent_id, None)
    if worker:
        if worker.polling_task:
            worker.polling_task.cancel()
        worker.stream_reader.cancel()
        container_name = f"rhclaw-{agent_id[:8]}"
        await kill_container(container_name)
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        await db.execute(
            "UPDATE agent_containers SET status = 'stopped', stopped_at = ? "
            "WHERE id = ?",
            (now, worker.container_record_id),
        )

    await db.execute(
        "UPDATE agents SET status = 'archived' WHERE id = ?", (agent_id,),
    )
    await db.commit()
    return {"status": "ok", "agent_id": agent_id}


# --- Agent Files API ---

IDENTITY_FILES = {"CLAUDE.md", "SOUL.md", "MEMORY.md"}
IDENTITY_TO_COLUMN = {
    "CLAUDE.md": "claude_md",
    "SOUL.md": "soul_md",
    "MEMORY.md": "memory_md",
}


async def _resolve_agent_path(
    agent_id: str, rel_path: str = "",
) -> tuple[Path, Path]:
    """Return (host_dir, resolved_path) or raise HTTPException."""
    db = await get_db()
    async with db.execute(
        "SELECT host_dir FROM agents WHERE id = ? AND status = 'active'",
        (agent_id,),
    ) as cur:
        row = await cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Agent not found")

    host_dir = Path(row[0]).resolve()
    resolved = (host_dir / rel_path).resolve() if rel_path else host_dir
    if not resolved.is_relative_to(host_dir):
        raise HTTPException(status_code=403, detail="Path traversal denied")
    return host_dir, resolved


@router.get("/agents/{agent_id}/files")
async def list_agent_files(
    agent_id: str, path: str = "",
) -> list[FileEntry]:
    host_dir, resolved = await _resolve_agent_path(agent_id, path)
    if not resolved.is_dir():
        raise HTTPException(status_code=404, detail="Directory not found")

    entries = []
    for item in sorted(resolved.iterdir()):
        rel = str(item.relative_to(host_dir))
        stat = item.stat()
        entries.append(FileEntry(
            name=item.name,
            path=rel,
            type="directory" if item.is_dir() else "file",
            size=stat.st_size if item.is_file() else None,
            modified_at=time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime(stat.st_mtime)
            ),
        ))
    return entries


@router.get("/agents/{agent_id}/files/{file_path:path}")
async def read_agent_file(agent_id: str, file_path: str):
    from fastapi.responses import PlainTextResponse

    _, resolved = await _resolve_agent_path(agent_id, file_path)
    if not resolved.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return PlainTextResponse(resolved.read_text())


@router.put("/agents/{agent_id}/files/{file_path:path}")
async def write_agent_file(agent_id: str, file_path: str, request: Request):
    host_dir, resolved = await _resolve_agent_path(agent_id, file_path)
    body = await request.body()
    content = body.decode("utf-8")

    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(content)

    # Sync identity files to the agents table
    filename = resolved.name
    if filename in IDENTITY_TO_COLUMN:
        column = IDENTITY_TO_COLUMN[filename]
        db = await get_db()
        await db.execute(
            f"UPDATE agents SET {column} = ? WHERE id = ?",
            (content, agent_id),
        )
        await db.commit()

    return {"status": "ok", "path": file_path, "size": len(content)}


@router.delete("/agents/{agent_id}/files/{file_path:path}")
async def delete_agent_file(agent_id: str, file_path: str):
    _, resolved = await _resolve_agent_path(agent_id, file_path)

    if resolved.name in IDENTITY_FILES:
        raise HTTPException(status_code=403, detail="Cannot delete identity files")
    if not resolved.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    resolved.unlink()
    return {"status": "ok", "path": file_path}


# --- Containers API ---


@router.get("/containers")
async def list_containers() -> list[ContainerResponse]:
    db = await get_db()
    async with db.execute(
        "SELECT c.id, c.agent_id, a.name, c.session_id, c.container_type, "
        "c.status, c.started_at, c.stopped_at, c.last_activity, c.pid "
        "FROM agent_containers c "
        "LEFT JOIN agents a ON a.id = c.agent_id "
        "ORDER BY c.started_at DESC"
    ) as cur:
        rows = await cur.fetchall()
    return [
        ContainerResponse(
            id=r[0], agent_id=r[1], agent_name=r[2], session_id=r[3],
            container_type=r[4], status=r[5], started_at=r[6],
            stopped_at=r[7], last_activity=r[8], pid=r[9],
        )
        for r in rows
    ]


@router.get("/containers/{container_id}/logs")
async def get_container_logs(container_id: str, tail: int = 100):
    db = await get_db()
    async with db.execute(
        "SELECT c.agent_id FROM agent_containers c WHERE c.id = ?",
        (container_id,),
    ) as cur:
        row = await cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Container not found")

    agent_id = row[0]
    container_name = f"rhclaw-{agent_id[:8]}"

    try:
        proc = await asyncio.create_subprocess_exec(
            "/opt/podman/bin/podman", "logs", "--tail", str(tail), container_name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        logs = stdout.decode() + stderr.decode()
    except Exception as e:
        logs = f"Error fetching logs: {e}"

    from fastapi.responses import PlainTextResponse
    return PlainTextResponse(logs)


@router.delete("/containers/{container_id}")
async def delete_container(container_id: str):
    db = await get_db()
    async with db.execute(
        "SELECT c.id, c.agent_id, c.status FROM agent_containers c WHERE c.id = ?",
        (container_id,),
    ) as cur:
        row = await cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Container not found")

    record_id, agent_id, status = row

    if status in ("running", "idle", "starting"):
        container_name = f"rhclaw-{agent_id[:8]}"
        await kill_container(container_name)

    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    await db.execute(
        "UPDATE agent_containers SET status = 'stopped', stopped_at = ? WHERE id = ?",
        (now, record_id),
    )
    await db.commit()

    # Clean up in-memory state
    worker = _active_workers.pop(agent_id, None)
    if worker:
        if worker.polling_task:
            worker.polling_task.cancel()
        worker.stream_reader.cancel()

    return {"status": "ok", "container_id": container_id}


# --- Message History API ---


@router.get("/agents/{agent_id}/messages")
async def get_agent_messages(agent_id: str, limit: int = 100):
    """Return recent messages for an agent across all its sessions."""
    db = await get_db()
    async with db.execute(
        "SELECT m.id, m.role, m.content, m.created_at "
        "FROM messages m "
        "JOIN sessions s ON s.id = m.session_id "
        "WHERE s.agent_id = ? "
        "ORDER BY m.created_at DESC LIMIT ?",
        (agent_id, limit),
    ) as cur:
        rows = await cur.fetchall()

    # Return in chronological order
    return [
        {"id": r[0], "role": r[1], "content": r[2], "created_at": r[3]}
        for r in reversed(rows)
    ]


@router.delete("/agents/{agent_id}/messages")
async def clear_agent_messages(agent_id: str):
    """Delete all messages for an agent (used by Clear Context)."""
    db = await get_db()
    await db.execute(
        "DELETE FROM messages WHERE session_id IN "
        "(SELECT id FROM sessions WHERE agent_id = ?)",
        (agent_id,),
    )
    await db.commit()
    return {"status": "ok"}


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
    worker = _active_workers.get(agent_id)

    if worker:
        # Container already running — reattach WebSocket
        if worker.polling_task:
            worker.polling_task.cancel()

        worker.session_id = session_id
        worker.stream_reader.attach(ws, session_id)
        worker.polling_task = start_polling_loop(session_id, worker.host_dir, ws)

        # Mark as running again (was idle)
        db = await get_db()
        await db.execute(
            "UPDATE agent_containers SET status = 'running', session_id = ? WHERE id = ?",
            (session_id, worker.container_record_id),
        )
        await db.commit()
        return

    record_id, process, host_dir = await spawn_container(agent_id, session_id)
    reader = StreamReader(process, session_id)
    reader.attach(ws, session_id)
    reader.start()

    _active_workers[agent_id] = WorkerState(
        container_record_id=record_id,
        process=process,
        host_dir=host_dir,
        session_id=session_id,
        stream_reader=reader,
        polling_task=start_polling_loop(session_id, host_dir, ws),
    )


async def _cleanup_session(agent_id: str, session_id: str) -> None:
    """Detach WebSocket resources on disconnect. Container keeps running."""
    worker = _active_workers.get(agent_id)
    if worker and worker.session_id == session_id:
        if worker.polling_task:
            worker.polling_task.cancel()
            worker.polling_task = None
        worker.stream_reader.detach()

        # Mark as idle — reaper will kill after timeout
        db = await get_db()
        await db.execute(
            "UPDATE agent_containers SET status = 'idle' WHERE id = ?",
            (worker.container_record_id,),
        )
        await db.commit()

    _rate_limits.pop(session_id, None)


async def _reap_idle_workers() -> None:
    """Background task: kill worker containers idle longer than IDLE_TIMEOUT_SECONDS.

    Activity is tracked by last_activity in agent_containers (updated when
    messages are flushed via IPC, not on WebSocket connect/disconnect).
    """
    while True:
        await asyncio.sleep(30)
        try:
            db = await get_db()
            cutoff = time.strftime(
                "%Y-%m-%dT%H:%M:%SZ",
                time.gmtime(time.time() - IDLE_TIMEOUT_SECONDS),
            )
            async with db.execute(
                "SELECT id, agent_id FROM agent_containers "
                "WHERE status = 'idle' AND last_activity < ?",
                (cutoff,),
            ) as cur:
                rows = await cur.fetchall()

            for record_id, agent_id in rows:
                container_name = f"rhclaw-{agent_id[:8]}"
                logger.info("Reaping idle container %s for agent %s", container_name, agent_id)
                await kill_container(container_name)

                now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                await db.execute(
                    "UPDATE agent_containers SET status = 'stopped', stopped_at = ? WHERE id = ?",
                    (now, record_id),
                )
                await db.commit()

                # Clean up in-memory state
                worker = _active_workers.pop(agent_id, None)
                if worker:
                    if worker.polling_task:
                        worker.polling_task.cancel()
                    worker.stream_reader.cancel()

        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Idle reaper error")


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
            except json.JSONDecodeError:
                error = ErrorFrame(code="QUEUE_FULL")
                await ws.send_text(error.model_dump_json())
                continue

            if data.get("type") == "system_command":
                try:
                    cmd_frame = SystemCommandFrame.model_validate(data)
                    await queue_system_command(session_id, cmd_frame.command)
                    await _send_queue_status(ws, session_id)
                    await _ensure_worker(agent_id, session_id, ws)
                except ValidationError:
                    error = ErrorFrame(code="QUEUE_FULL")
                    await ws.send_text(error.model_dump_json())
                continue

            try:
                frame = UserMessageFrame.model_validate(data)
            except ValidationError:
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
        await _cleanup_session(agent_id, session_id)
