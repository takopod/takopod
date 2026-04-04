import asyncio
import dataclasses
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
    atomic_write,
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
    SystemErrorFrame,
    UpdateAgentRequest,
    UserMessageFrame,
)
from orchestrator.settings import get_all_settings, get_setting, set_setting
from orchestrator.ws_manager import WS_CLOSE_ADMIN_KILL, WS_CLOSE_IDLE_TIMEOUT, WebSocketManager

router = APIRouter(prefix="/api")

RATE_LIMIT_WINDOW = 60
RATE_LIMIT_MAX = 10
QUEUE_DEPTH_MAX = 50
IDLE_TIMEOUT_SECONDS = int(os.environ.get("IDLE_TIMEOUT_SECONDS", "300"))  # 5 minutes
CIRCUIT_BREAKER_WINDOW = 600  # 10 minutes
CIRCUIT_BREAKER_MAX_CRASHES = 3

_rate_limits: dict[str, deque[float]] = defaultdict(deque)


logger = logging.getLogger(__name__)


@dataclass
class WorkerState:
    """Tracks a running worker container for an agent."""
    container_record_id: str
    process: asyncio.subprocess.Process
    host_dir: Path
    session_id: str
    ws_manager: WebSocketManager
    polling_task: asyncio.Task | None = None
    monitor_task: asyncio.Task | None = None
    crash_times: deque = dataclasses.field(default_factory=deque)
    shutting_down: bool = False


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
        "SELECT a.id, a.name, a.agent_type, a.status, a.created_at, "
        "  (SELECT c.status FROM agent_containers c "
        "   WHERE c.agent_id = a.id ORDER BY c.started_at DESC LIMIT 1) AS container_status, "
        "  (SELECT COUNT(*) FROM sessions s "
        "   JOIN agent_containers ac ON ac.session_id = s.id "
        "   WHERE ac.agent_id = a.id AND ac.status IN ('running', 'idle', 'starting')) "
        "   AS active_session_count "
        "FROM agents a WHERE a.status = 'active' ORDER BY a.created_at"
    ) as cur:
        rows = await cur.fetchall()
    return [
        AgentResponse(
            id=r[0], name=r[1], agent_type=r[2], status=r[3], created_at=r[4],
            container_status=r[5], active_session_count=r[6] or 0,
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
        if worker.monitor_task:
            worker.monitor_task.cancel()
        container_name = f"rhclaw-{agent_id[:8]}"
        await kill_container(container_name)

    # Mark ALL running/starting containers for this agent as stopped,
    # regardless of whether we had an active worker reference.
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    await db.execute(
        "UPDATE agent_containers SET status = 'stopped', stopped_at = ? "
        "WHERE agent_id = ? AND status IN ('running', 'starting', 'idle')",
        (now, agent_id),
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
        if worker.monitor_task:
            worker.monitor_task.cancel()

    return {"status": "ok", "container_id": container_id}


# --- Sessions API ---


@router.post("/sessions/{session_id}/kill")
async def kill_session(session_id: str):
    """Force-terminate a session: graceful shutdown with 10s timeout, then kill."""
    db = await get_db()
    async with db.execute(
        "SELECT c.id, c.agent_id FROM agent_containers c "
        "WHERE c.session_id = ? AND c.status IN ('running', 'idle', 'starting', 'stopping')",
        (session_id,),
    ) as cur:
        row = await cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="No active container for session")

    record_id, agent_id = row
    container_name = f"rhclaw-{agent_id[:8]}"
    worker = _active_workers.get(agent_id)
    graceful = False

    if worker:
        worker.shutting_down = True
        # Try graceful shutdown
        try:
            input_path = worker.host_dir / "input.json"
            shutdown_payload = json.dumps(
                [{"type": "system_command", "command": "shutdown"}]
            )
            atomic_write(input_path, shutdown_payload.encode())
            await asyncio.wait_for(worker.process.wait(), timeout=10)
            graceful = True
        except (asyncio.TimeoutError, Exception):
            await kill_container(container_name)

        # Notify connected client
        if worker.ws_manager.connected:
            try:
                await worker.ws_manager.send(
                    SystemErrorFrame(
                        error="Session terminated by admin", fatal=True,
                    ).model_dump_json()
                )
            except Exception:
                pass
            await worker.ws_manager.close(WS_CLOSE_ADMIN_KILL, "Terminated by admin")
    else:
        await kill_container(container_name)

    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    await db.execute(
        "UPDATE agent_containers SET status = 'stopped', stopped_at = ? WHERE id = ?",
        (now, record_id),
    )
    await db.execute(
        "UPDATE sessions SET status = 'terminated', ended_at = ? "
        "WHERE id = ? AND ended_at IS NULL",
        (now, session_id),
    )
    await db.commit()

    # Clean up in-memory state
    w = _active_workers.pop(agent_id, None)
    if w:
        if w.polling_task:
            w.polling_task.cancel()
        if w.monitor_task:
            w.monitor_task.cancel()

    return {"status": "ok", "session_id": session_id, "graceful": graceful}


@router.get("/sessions")
async def list_sessions(status: str | None = None, limit: int = 50):
    """List sessions, optionally filtered by status."""
    db = await get_db()
    query = (
        "SELECT s.id, s.agent_id, a.name, s.status, s.created_at, s.ended_at "
        "FROM sessions s LEFT JOIN agents a ON a.id = s.agent_id "
    )
    params: list = []
    if status:
        query += "WHERE s.status = ? "
        params.append(status)
    query += "ORDER BY s.created_at DESC LIMIT ?"
    params.append(limit)

    async with db.execute(query, params) as cur:
        rows = await cur.fetchall()

    return [
        {
            "id": r[0], "agent_id": r[1], "agent_name": r[2],
            "status": r[3], "created_at": r[4], "ended_at": r[5],
        }
        for r in rows
    ]


@router.get("/sessions/{session_id}")
async def get_session(session_id: str):
    """Detailed session state: metadata, container info, message queue breakdown."""
    db = await get_db()
    async with db.execute(
        "SELECT s.id, s.agent_id, a.name, s.status, s.created_at, s.ended_at "
        "FROM sessions s LEFT JOIN agents a ON a.id = s.agent_id "
        "WHERE s.id = ?",
        (session_id,),
    ) as cur:
        row = await cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Session not found")

    session = {
        "id": row[0], "agent_id": row[1], "agent_name": row[2],
        "status": row[3], "created_at": row[4], "ended_at": row[5],
    }

    # Message queue breakdown
    async with db.execute(
        "SELECT status, COUNT(*) FROM message_queue "
        "WHERE session_id = ? GROUP BY status",
        (session_id,),
    ) as cur:
        queue_rows = await cur.fetchall()
    session["queue"] = {r[0]: r[1] for r in queue_rows}

    # Container info
    async with db.execute(
        "SELECT id, status, started_at, stopped_at, last_activity, error_message "
        "FROM agent_containers WHERE session_id = ? "
        "ORDER BY started_at DESC LIMIT 1",
        (session_id,),
    ) as cur:
        c_row = await cur.fetchone()
    if c_row:
        session["container"] = {
            "id": c_row[0], "status": c_row[1], "started_at": c_row[2],
            "stopped_at": c_row[3], "last_activity": c_row[4],
            "error_message": c_row[5],
        }

    # Message count
    async with db.execute(
        "SELECT COUNT(*) FROM messages WHERE session_id = ?",
        (session_id,),
    ) as cur:
        session["message_count"] = (await cur.fetchone())[0]

    return session


# --- Settings API ---


@router.get("/settings")
async def list_settings():
    return await get_all_settings()


@router.put("/settings/{key}")
async def update_setting(key: str, request: Request):
    body = await request.json()
    value = body.get("value")
    if value is None:
        raise HTTPException(status_code=400, detail="Missing 'value' field")
    await set_setting(key, str(value))
    return {"key": key, "value": str(value)}


# --- Message History API ---


@router.get("/agents/{agent_id}/messages")
async def get_agent_messages(agent_id: str, limit: int = 100):
    """Return recent messages for an agent across all its sessions."""
    db = await get_db()
    async with db.execute(
        "SELECT m.id, m.role, m.content, m.created_at, m.metadata, m.status "
        "FROM messages m "
        "JOIN sessions s ON s.id = m.session_id "
        "WHERE s.agent_id = ? "
        "ORDER BY m.created_at DESC LIMIT ?",
        (agent_id, limit),
    ) as cur:
        rows = await cur.fetchall()

    # Return in chronological order
    return [
        {
            "id": r[0], "role": r[1], "content": r[2],
            "created_at": r[3], "metadata": r[4], "status": r[5],
        }
        for r in reversed(rows)
    ]


@router.get("/agents/{agent_id}/messages/{message_id}")
async def get_agent_message(agent_id: str, message_id: str):
    """Return a single message by ID, scoped to an agent."""
    db = await get_db()
    async with db.execute(
        "SELECT m.id, m.role, m.content, m.created_at, m.metadata, m.status "
        "FROM messages m "
        "JOIN sessions s ON s.id = m.session_id "
        "WHERE m.id = ? AND s.agent_id = ?",
        (message_id, agent_id),
    ) as cur:
        row = await cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Message not found")
    return {
        "id": row[0], "role": row[1], "content": row[2],
        "created_at": row[3], "metadata": row[4], "status": row[5],
    }


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


async def _send_queue_status(ws: WebSocket, session_id: str, agent_id: str) -> None:
    counts = await get_queue_counts(session_id)
    status = QueueStatusFrame(**counts)
    worker = _active_workers.get(agent_id)
    if worker:
        await worker.ws_manager.send(status.model_dump_json())
    else:
        await ws.send_text(status.model_dump_json())


async def _ensure_worker(
    agent_id: str, session_id: str, ws: WebSocket
) -> None:
    worker = _active_workers.get(agent_id)

    if worker:
        # Container already running — reattach WebSocket
        if worker.polling_task:
            worker.polling_task.cancel()
        if worker.monitor_task:
            worker.monitor_task.cancel()

        worker.session_id = session_id
        worker.ws_manager.attach(ws, session_id)
        worker.polling_task = start_polling_loop(session_id, worker.host_dir, worker.ws_manager)
        worker.monitor_task = asyncio.create_task(
            _monitor_worker(agent_id), name=f"monitor-{agent_id[:8]}",
        )

        # Mark as running again (was idle)
        db = await get_db()
        await db.execute(
            "UPDATE agent_containers SET status = 'running', session_id = ? WHERE id = ?",
            (session_id, worker.container_record_id),
        )
        await db.commit()
        return

    record_id, process, host_dir = await spawn_container(agent_id, session_id)
    ws_mgr = WebSocketManager(session_id)
    ws_mgr.attach(ws, session_id)

    worker = WorkerState(
        container_record_id=record_id,
        process=process,
        host_dir=host_dir,
        session_id=session_id,
        ws_manager=ws_mgr,
        polling_task=start_polling_loop(session_id, host_dir, ws_mgr),
    )
    _active_workers[agent_id] = worker
    worker.monitor_task = asyncio.create_task(
        _monitor_worker(agent_id), name=f"monitor-{agent_id[:8]}",
    )


async def _cleanup_session(agent_id: str, session_id: str) -> None:
    """Detach WebSocket resources on disconnect. Container keeps running."""
    worker = _active_workers.get(agent_id)
    if worker and worker.session_id == session_id:
        if worker.polling_task:
            worker.polling_task.cancel()
            worker.polling_task = None
        if worker.monitor_task:
            worker.monitor_task.cancel()
            worker.monitor_task = None
        worker.ws_manager.detach()

        # Mark container as idle — reaper will kill after timeout
        db = await get_db()
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        await db.execute(
            "UPDATE agent_containers SET status = 'idle' WHERE id = ?",
            (worker.container_record_id,),
        )
        # Mark session as disconnected (container still alive, user may reconnect)
        await db.execute(
            "UPDATE sessions SET status = 'disconnected', ended_at = ? "
            "WHERE id = ? AND ended_at IS NULL",
            (now, session_id),
        )
        await db.commit()

    _rate_limits.pop(session_id, None)


async def _respawn_worker(agent_id: str) -> None:
    """Respawn a crashed worker container for the same agent."""
    worker = _active_workers.get(agent_id)
    if not worker:
        return

    try:
        await worker.ws_manager.send(
            SystemErrorFrame(
                error="Agent restarting after crash...", fatal=False,
            ).model_dump_json()
        )
    except Exception:
        pass

    try:
        record_id, process, host_dir = await spawn_container(
            agent_id, worker.session_id,
        )
        worker.container_record_id = record_id
        worker.process = process
        worker.host_dir = host_dir
        worker.polling_task = start_polling_loop(
            worker.session_id, host_dir, worker.ws_manager,
        )
        worker.monitor_task = asyncio.create_task(
            _monitor_worker(agent_id), name=f"monitor-{agent_id[:8]}",
        )
        logger.info("Respawned worker for agent %s", agent_id)
    except Exception:
        logger.exception("Failed to respawn worker for agent %s", agent_id)
        try:
            await worker.ws_manager.send(
                SystemErrorFrame(
                    error="Agent failed to restart", fatal=True,
                ).model_dump_json()
            )
        except Exception:
            pass
        _active_workers.pop(agent_id, None)


async def _monitor_worker(agent_id: str) -> None:
    """Await worker process exit and handle crash recovery."""
    worker = _active_workers.get(agent_id)
    if not worker:
        return

    returncode = await worker.process.wait()

    # Process exited — check if we still own this agent
    current = _active_workers.get(agent_id)
    if current is not worker:
        return  # Worker was replaced (e.g., by _ensure_worker)

    # Clean shutdown initiated by reaper or admin kill — skip crash recovery
    if worker.shutting_down:
        logger.info(
            "Worker for agent %s shut down cleanly (code %s)", agent_id, returncode,
        )
        return  # Reaper/admin kill handles cleanup

    logger.warning(
        "Worker for agent %s exited with code %s", agent_id, returncode,
    )

    # Cancel polling loop
    if worker.polling_task:
        worker.polling_task.cancel()
        worker.polling_task = None

    # Clean up dead container
    container_name = f"rhclaw-{agent_id[:8]}"
    await kill_container(container_name)

    # Update DB status
    db = await get_db()
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    await db.execute(
        "UPDATE agent_containers SET status = 'error', stopped_at = ?, "
        "error_message = ? WHERE id = ?",
        (now, f"Process exited with code {returncode}", worker.container_record_id),
    )
    await db.commit()

    # Check if WebSocket is connected
    if not worker.ws_manager.connected:
        logger.info(
            "No WebSocket connected for agent %s — skipping respawn", agent_id,
        )
        _active_workers.pop(agent_id, None)
        return

    # Circuit breaker: prune old crash times, then check
    cutoff = time.monotonic() - CIRCUIT_BREAKER_WINDOW
    while worker.crash_times and worker.crash_times[0] < cutoff:
        worker.crash_times.popleft()
    worker.crash_times.append(time.monotonic())

    if len(worker.crash_times) >= CIRCUIT_BREAKER_MAX_CRASHES:
        logger.error(
            "Circuit breaker triggered for agent %s: %d crashes in %ds",
            agent_id, len(worker.crash_times), CIRCUIT_BREAKER_WINDOW,
        )
        try:
            await worker.ws_manager.send(
                SystemErrorFrame(
                    error="Agent unavailable after repeated failures. Refresh to retry.",
                    fatal=True,
                ).model_dump_json()
            )
        except Exception:
            pass
        _active_workers.pop(agent_id, None)
        return

    # Respawn
    await _respawn_worker(agent_id)


async def _reap_idle_workers() -> None:
    """Background task: gracefully shut down worker containers idle longer than
    IDLE_TIMEOUT_SECONDS.

    Flow per container: send shutdown command via input.json → wait up to 60s
    for clean exit → force-kill on timeout. Specific failure reasons are
    propagated to the WebSocket client so the user knows exactly what happened.
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
                "SELECT id, agent_id, session_id FROM agent_containers "
                "WHERE status = 'idle' AND last_activity < ?",
                (cutoff,),
            ) as cur:
                rows = await cur.fetchall()

            for record_id, agent_id, session_id in rows:
                container_name = f"rhclaw-{agent_id[:8]}"
                worker = _active_workers.get(agent_id)
                reason = "Session ended due to inactivity"
                graceful = False

                if worker:
                    worker.shutting_down = True

                    # Try graceful shutdown via input.json
                    try:
                        input_path = worker.host_dir / "input.json"
                        shutdown_payload = json.dumps(
                            [{"type": "system_command", "command": "shutdown"}]
                        )
                        atomic_write(input_path, shutdown_payload.encode())

                        logger.info(
                            "Sending shutdown to idle worker %s for agent %s",
                            container_name, agent_id,
                        )

                        await db.execute(
                            "UPDATE agent_containers SET status = 'stopping' WHERE id = ?",
                            (record_id,),
                        )
                        await db.commit()

                        # Wait for worker to exit cleanly
                        try:
                            await asyncio.wait_for(worker.process.wait(), timeout=60)
                            graceful = True
                            logger.info("Worker %s exited gracefully", container_name)
                        except asyncio.TimeoutError:
                            reason = "Session ended — worker did not respond to shutdown, container was force-stopped"
                            logger.warning(
                                "Worker %s did not exit in 60s, force-killing",
                                container_name,
                            )
                            await kill_container(container_name)
                    except Exception:
                        reason = "Session ended — cleanup error, container was force-stopped"
                        logger.exception(
                            "Failed to send shutdown to worker %s, force-killing",
                            container_name,
                        )
                        await kill_container(container_name)
                else:
                    # No in-memory worker (e.g. orchestrator restarted) — hard kill
                    logger.info(
                        "Reaping idle container %s (no in-memory state)", container_name,
                    )
                    await kill_container(container_name)

                # Finalize DB state
                now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                await db.execute(
                    "UPDATE agent_containers SET status = 'stopped', stopped_at = ? "
                    "WHERE id = ?",
                    (now, record_id),
                )
                await db.execute(
                    "UPDATE sessions SET status = 'idle_timeout', ended_at = ? "
                    "WHERE id = ? AND ended_at IS NULL",
                    (now, session_id),
                )
                await db.commit()

                # Notify WebSocket client if still connected
                if worker and worker.ws_manager.connected:
                    try:
                        await worker.ws_manager.send(
                            SystemErrorFrame(error=reason, fatal=True).model_dump_json()
                        )
                    except Exception:
                        pass
                    await worker.ws_manager.close(
                        WS_CLOSE_IDLE_TIMEOUT, "Idle timeout",
                    )

                # Clean up in-memory state
                w = _active_workers.pop(agent_id, None)
                if w:
                    if w.polling_task:
                        w.polling_task.cancel()
                    if w.monitor_task:
                        w.monitor_task.cancel()

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
                    await _send_queue_status(ws, session_id, agent_id)
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

            # Reset idle timer on every user message
            worker = _active_workers.get(agent_id)
            if worker:
                now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                db = await get_db()
                await db.execute(
                    "UPDATE agent_containers SET last_activity = ? WHERE id = ?",
                    (now, worker.container_record_id),
                )
                await db.commit()

            await _send_queue_status(ws, session_id, agent_id)
            await _ensure_worker(agent_id, session_id, ws)

    except WebSocketDisconnect:
        await _cleanup_session(agent_id, session_id)
