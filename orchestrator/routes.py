import asyncio
import dataclasses
import json
import logging
import os
import re
import shutil
import sys
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path

from fastapi import (
    APIRouter,
    HTTPException,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import FileResponse
from pydantic import ValidationError

from orchestrator.container_manager import (
    MCP_CONFIGS_DIR,
    create_agent_workspace,
    kill_container,
    spawn_container,
)
from orchestrator.mcp_manager import McpServerManager
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
    CreateSkillRequest,
    ErrorFrame,
    FileEntry,
    McpConfigRequest,
    QueueStatusFrame,
    ScheduleResponse,
    SkillDetail,
    SkillSummary,
    SystemCommandFrame,
    SystemErrorFrame,
    ToolConfigRequest,
    UpdateAgentRequest,
    UpdateSkillRequest,
    UserMessageFrame,
)
from orchestrator.settings import get_all_settings, get_setting, set_setting
from orchestrator.slack_routes import router as slack_router
from orchestrator.slack_routes import _read_slack_config
from orchestrator.github_routes import router as github_router
from orchestrator.github_routes import _read_github_config
from orchestrator.search_routes import router as search_router
from orchestrator.ws_manager import WS_CLOSE_ADMIN_KILL, WebSocketManager

router = APIRouter(prefix="/api")
router.include_router(slack_router)
router.include_router(github_router)
router.include_router(search_router)

RATE_LIMIT_WINDOW = 60
RATE_LIMIT_MAX = 10
QUEUE_DEPTH_MAX = 50
CIRCUIT_BREAKER_WINDOW = 600  # 10 minutes
CIRCUIT_BREAKER_MAX_CRASHES = 3

_rate_limits: dict[str, deque[float]] = defaultdict(deque)


logger = logging.getLogger(__name__)


async def _cancel_task(task: asyncio.Task | None) -> None:
    """Cancel a task and wait for it to finish."""
    if task is None or task.done():
        return
    task.cancel()
    try:
        await task
    except (asyncio.CancelledError, Exception):
        pass


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
    mcp_manager: McpServerManager | None = None
    crash_times: deque = dataclasses.field(default_factory=deque)
    shutting_down: bool = False


# Keyed by agent_id — one worker per agent
_active_workers: dict[str, WorkerState] = {}
_workers_lock = asyncio.Lock()


async def _start_mcp_manager(host_dir: Path, agent_id: str) -> McpServerManager | None:
    """Start host-side MCP servers if configured, write tool schemas to workspace."""
    config_path = MCP_CONFIGS_DIR / f"{agent_id}.json"
    if not config_path.is_file():
        # Fallback: check legacy locations
        for legacy in (host_dir / "config" / ".mcp.json", host_dir / ".mcp.json"):
            if legacy.is_file():
                config_path = legacy
                break
        else:
            config_path = None

    mcp_config: dict = {"mcpServers": {}}
    if config_path:
        try:
            mcp_config = json.loads(config_path.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    mcp_config.setdefault("mcpServers", {})

    # Inject Slack MCP server if globally configured and enabled for this agent
    slack_config = _read_slack_config()
    if slack_config:
        db = await get_db()
        async with db.execute(
            "SELECT slack_enabled FROM agents WHERE id = ?", (agent_id,),
        ) as cur:
            row = await cur.fetchone()
        if row and row[0]:
            mcp_config["mcpServers"]["slack"] = {
                "command": sys.executable,
                "args": ["-m", "integrations.slack_mcp"],
                "env": {
                    "SLACK_XOXC_TOKEN": slack_config["xoxc_token"],
                    "SLACK_D_COOKIE": slack_config["d_cookie"],
                    "MY_MEMBER_ID": slack_config.get("member_id", ""),
                },
                "timeout": 30.0,
            }
            logger.info("Injected Slack MCP server for agent %s", agent_id)

    # Inject GitHub MCP server if globally configured and enabled for this agent
    github_config = _read_github_config()
    if github_config:
        db = await get_db()
        async with db.execute(
            "SELECT github_enabled FROM agents WHERE id = ?", (agent_id,),
        ) as cur:
            gh_row = await cur.fetchone()
        if gh_row and gh_row[0]:
            mcp_config["mcpServers"]["github"] = {
                "command": sys.executable,
                "args": ["-m", "integrations.github_mcp"],
                "env": {
                    "GITHUB_PERSONAL_ACCESS_TOKEN": github_config["personal_access_token"],
                    "GITHUB_USERNAME": github_config.get("username", ""),
                },
                "timeout": 30.0,
            }
            logger.info("Injected GitHub MCP server for agent %s", agent_id)

    if not mcp_config["mcpServers"]:
        return None

    manager = McpServerManager()
    await manager.start(mcp_config)

    schemas = manager.get_tool_schemas()
    if schemas:
        tools_path = host_dir / "mcp_tools.json"
        tools_path.write_text(json.dumps(schemas, indent=2))
        logger.info("Wrote %d MCP tool schemas to %s", len(schemas), tools_path)

    return manager


# --- Agent Templates ---

TEMPLATES_DIR = Path("agent_templates")


@router.get("/templates")
async def list_templates():
    """List available agent templates."""
    templates = []
    if TEMPLATES_DIR.is_dir():
        for d in sorted(TEMPLATES_DIR.iterdir()):
            if d.is_dir():
                templates.append({"id": d.name, "name": d.name})
    return templates


# --- Agent CRUD ---


@router.post("/agents")
async def create_agent(req: CreateAgentRequest) -> AgentResponse:
    db = await get_db()
    agent_id = str(uuid.uuid4())
    host_dir = create_agent_workspace(agent_id, req.agent_type)

    await db.execute(
        "INSERT INTO agents (id, name, agent_type, host_dir, slack_enabled, github_enabled) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (agent_id, req.name, req.agent_type, str(host_dir),
         1 if req.slack_enabled else 0, 1 if req.github_enabled else 0),
    )
    await db.commit()

    async with db.execute(
        "SELECT id, name, agent_type, status, created_at, slack_enabled, github_enabled "
        "FROM agents WHERE id = ?",
        (agent_id,),
    ) as cur:
        row = await cur.fetchone()

    return AgentResponse(
        id=row[0], name=row[1], agent_type=row[2], status=row[3], created_at=row[4],
        slack_enabled=bool(row[5]), github_enabled=bool(row[6]),
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
        "   AS active_session_count, "
        "  a.slack_enabled, "
        "  a.github_enabled "
        "FROM agents a WHERE a.status = 'active' ORDER BY a.created_at"
    ) as cur:
        rows = await cur.fetchall()
    return [
        AgentResponse(
            id=r[0], name=r[1], agent_type=r[2], status=r[3], created_at=r[4],
            container_status=r[5], active_session_count=r[6] or 0,
            slack_enabled=bool(r[7]), github_enabled=bool(r[8]),
        )
        for r in rows
    ]


@router.get("/agents/{agent_id}")
async def get_agent(agent_id: str) -> AgentDetailResponse:
    db = await get_db()
    async with db.execute(
        "SELECT id, name, agent_type, status, created_at, host_dir, slack_enabled, github_enabled "
        "FROM agents WHERE id = ?",
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
        slack_enabled=bool(row[6]), github_enabled=bool(row[7]),
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
    async with _workers_lock:
        worker = _active_workers.pop(agent_id, None)
        if worker:
            old_polling = worker.polling_task
            old_monitor = worker.monitor_task
            worker.polling_task = None
            worker.monitor_task = None
    if worker:
        await _cancel_task(old_polling)
        await _cancel_task(old_monitor)
        if worker.mcp_manager:
            await worker.mcp_manager.stop()
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


# --- MCP Config API ---

VALID_BUILTIN_TOOLS = {
    "Read", "Write", "Edit", "Bash",
    "Glob", "Grep", "WebSearch", "WebFetch",
}


@router.get("/agents/{agent_id}/mcp")
async def get_mcp_config(agent_id: str):
    await _resolve_agent_path(agent_id)  # validates agent exists
    mcp_path = MCP_CONFIGS_DIR / f"{agent_id}.json"
    if not mcp_path.is_file():
        return {"mcpServers": {}}
    return json.loads(mcp_path.read_text())


@router.put("/agents/{agent_id}/mcp")
async def put_mcp_config(agent_id: str, req: McpConfigRequest):
    await _resolve_agent_path(agent_id)  # validates agent exists
    MCP_CONFIGS_DIR.mkdir(parents=True, exist_ok=True)
    mcp_path = MCP_CONFIGS_DIR / f"{agent_id}.json"
    data = req.model_dump(exclude_defaults=True)
    # Always include the top-level key
    data.setdefault("mcpServers", {})
    mcp_path.write_text(json.dumps(data, indent=2))
    return data


@router.delete("/agents/{agent_id}/mcp/servers/{server_name}")
async def delete_mcp_server(agent_id: str, server_name: str):
    await _resolve_agent_path(agent_id)  # validates agent exists
    mcp_path = MCP_CONFIGS_DIR / f"{agent_id}.json"
    if not mcp_path.is_file():
        raise HTTPException(status_code=404, detail=f"Server '{server_name}' not found")
    config = json.loads(mcp_path.read_text())
    servers = config.get("mcpServers", {})
    if server_name not in servers:
        raise HTTPException(status_code=404, detail=f"Server '{server_name}' not found")
    del servers[server_name]
    mcp_path.write_text(json.dumps(config, indent=2))
    return {"status": "ok", "removed": server_name}


# --- Per-Agent Tool Config API ---


@router.get("/agents/{agent_id}/tools")
async def get_tool_config(agent_id: str):
    host_dir, _ = await _resolve_agent_path(agent_id)
    tools_path = host_dir / "tools.json"
    if not tools_path.is_file():
        return {"builtin": sorted(VALID_BUILTIN_TOOLS), "permission_mode": "acceptEdits"}
    return json.loads(tools_path.read_text())


@router.put("/agents/{agent_id}/tools")
async def put_tool_config(agent_id: str, req: ToolConfigRequest):
    invalid = set(req.builtin) - VALID_BUILTIN_TOOLS
    if invalid:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown tools: {', '.join(sorted(invalid))}. "
            f"Valid tools: {', '.join(sorted(VALID_BUILTIN_TOOLS))}",
        )
    host_dir, _ = await _resolve_agent_path(agent_id)
    tools_path = host_dir / "tools.json"
    data = req.model_dump()
    tools_path.write_text(json.dumps(data, indent=2))
    return data


# --- Skills API ---

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---", re.DOTALL)


def _parse_skill_frontmatter(content: str) -> tuple[str, str]:
    """Extract name and description from SKILL.md YAML frontmatter."""
    m = _FRONTMATTER_RE.match(content)
    if not m:
        return "", ""
    try:
        import yaml

        data = yaml.safe_load(m.group(1))
        if not isinstance(data, dict):
            return "", ""
        return str(data.get("name", "")), str(data.get("description", ""))
    except Exception:
        return "", ""


def _skills_dir(host_dir: Path) -> Path:
    return host_dir / ".claude" / "skills"


def _collect_supporting_files(skill_dir: Path) -> list[str]:
    """List supporting files in a skill directory (excludes SKILL.md)."""
    files: list[str] = []
    for p in sorted(skill_dir.rglob("*")):
        if p.is_file() and p.name != "SKILL.md":
            files.append(str(p.relative_to(skill_dir)))
    return files


@router.get("/agents/{agent_id}/skills")
async def list_skills(agent_id: str) -> list[SkillSummary]:
    host_dir, _ = await _resolve_agent_path(agent_id)
    sdir = _skills_dir(host_dir)
    if not sdir.is_dir():
        return []
    result: list[SkillSummary] = []
    for d in sorted(sdir.iterdir()):
        if not d.is_dir():
            continue
        skill_md = d / "SKILL.md"
        if not skill_md.is_file():
            continue
        name, desc = _parse_skill_frontmatter(skill_md.read_text())
        result.append(SkillSummary(
            id=d.name,
            name=name or d.name,
            description=desc,
        ))
    return result


@router.get("/agents/{agent_id}/skills/{skill_id}")
async def get_skill(agent_id: str, skill_id: str) -> SkillDetail:
    host_dir, _ = await _resolve_agent_path(agent_id)
    skill_dir = _skills_dir(host_dir) / skill_id
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        raise HTTPException(status_code=404, detail="Skill not found")
    content = skill_md.read_text()
    name, desc = _parse_skill_frontmatter(content)
    return SkillDetail(
        id=skill_id,
        name=name or skill_id,
        description=desc,
        content=content,
        files=_collect_supporting_files(skill_dir),
    )


@router.post("/agents/{agent_id}/skills")
async def create_skill(agent_id: str, req: CreateSkillRequest) -> SkillDetail:
    host_dir, _ = await _resolve_agent_path(agent_id)
    skill_dir = _skills_dir(host_dir) / req.name
    if skill_dir.exists():
        raise HTTPException(status_code=409, detail=f"Skill '{req.name}' already exists")
    skill_dir.mkdir(parents=True)

    content = req.content
    if not content.strip():
        content = (
            f"---\nname: {req.name}\n"
            f"description: {req.description}\n"
            f"---\n\n# {req.name}\n\nTODO: Add skill instructions here.\n"
        )
    (skill_dir / "SKILL.md").write_text(content)

    name, desc = _parse_skill_frontmatter(content)
    return SkillDetail(
        id=req.name,
        name=name or req.name,
        description=desc,
        content=content,
        files=[],
    )


@router.put("/agents/{agent_id}/skills/{skill_id}")
async def update_skill(agent_id: str, skill_id: str, req: UpdateSkillRequest) -> SkillDetail:
    host_dir, _ = await _resolve_agent_path(agent_id)
    skill_dir = _skills_dir(host_dir) / skill_id
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        raise HTTPException(status_code=404, detail="Skill not found")
    skill_md.write_text(req.content)
    name, desc = _parse_skill_frontmatter(req.content)
    return SkillDetail(
        id=skill_id,
        name=name or skill_id,
        description=desc,
        content=req.content,
        files=_collect_supporting_files(skill_dir),
    )


@router.delete("/agents/{agent_id}/skills/{skill_id}")
async def delete_skill(agent_id: str, skill_id: str):
    host_dir, _ = await _resolve_agent_path(agent_id)
    skill_dir = _skills_dir(host_dir) / skill_id
    if not skill_dir.is_dir():
        raise HTTPException(status_code=404, detail="Skill not found")
    shutil.rmtree(skill_dir)
    return {"status": "ok", "skill_id": skill_id}


@router.post("/agents/{agent_id}/skills/{skill_id}/files")
async def upload_skill_files(
    agent_id: str, skill_id: str, files: list[UploadFile],
):
    host_dir, _ = await _resolve_agent_path(agent_id)
    skill_dir = _skills_dir(host_dir) / skill_id
    if not skill_dir.is_dir():
        raise HTTPException(status_code=404, detail="Skill not found")

    uploaded: list[str] = []
    for f in files:
        if not f.filename:
            continue
        # Prevent path traversal
        rel = Path(f.filename)
        if ".." in rel.parts:
            raise HTTPException(status_code=400, detail=f"Invalid filename: {f.filename}")
        dest = skill_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        data = await f.read()
        dest.write_bytes(data)
        if rel.suffix in (".sh", ".py"):
            dest.chmod(0o755)
        uploaded.append(str(rel))

    return {"status": "ok", "uploaded": uploaded}


@router.get("/agents/{agent_id}/skills/{skill_id}/files/{file_path:path}")
async def get_skill_file(agent_id: str, skill_id: str, file_path: str):
    host_dir, _ = await _resolve_agent_path(agent_id)
    skill_dir = _skills_dir(host_dir) / skill_id
    if not skill_dir.is_dir():
        raise HTTPException(status_code=404, detail="Skill not found")
    target = (skill_dir / file_path).resolve()
    # Ensure target is within skill_dir (path traversal guard)
    if not str(target).startswith(str(skill_dir.resolve())):
        raise HTTPException(status_code=400, detail="Invalid file path")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(target)


@router.delete("/agents/{agent_id}/skills/{skill_id}/files/{file_path:path}")
async def delete_skill_file(agent_id: str, skill_id: str, file_path: str):
    host_dir, _ = await _resolve_agent_path(agent_id)
    skill_dir = _skills_dir(host_dir) / skill_id
    if not skill_dir.is_dir():
        raise HTTPException(status_code=404, detail="Skill not found")
    target = (skill_dir / file_path).resolve()
    if not str(target).startswith(str(skill_dir.resolve())):
        raise HTTPException(status_code=400, detail="Invalid file path")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    target.unlink()
    # Clean up empty parent directories
    parent = target.parent
    while parent != skill_dir and not any(parent.iterdir()):
        parent.rmdir()
        parent = parent.parent
    return {"status": "ok", "deleted": file_path}


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
    async with _workers_lock:
        worker = _active_workers.pop(agent_id, None)
        if worker:
            old_polling = worker.polling_task
            old_monitor = worker.monitor_task
            worker.polling_task = None
            worker.monitor_task = None
    if worker:
        await _cancel_task(old_polling)
        await _cancel_task(old_monitor)
        if worker.mcp_manager:
            await worker.mcp_manager.stop()

    return {"status": "ok", "container_id": container_id}


# --- Schedules API ---


@router.get("/schedules")
async def list_schedules(status: str | None = None) -> list[ScheduleResponse]:
    db = await get_db()
    query = (
        "SELECT t.id, t.agent_id, a.name, t.prompt, t.allowed_tools, "
        "t.interval_seconds, t.last_executed_at, t.last_result, t.status, t.created_at "
        "FROM agentic_tasks t "
        "LEFT JOIN agents a ON a.id = t.agent_id "
    )
    params: list = []
    if status:
        query += "WHERE t.status = ? "
        params.append(status)
    query += "ORDER BY t.created_at DESC"

    async with db.execute(query, params) as cur:
        rows = await cur.fetchall()

    return [
        ScheduleResponse(
            id=r[0], agent_id=r[1], agent_name=r[2] or "Unknown",
            prompt=r[3], allowed_tools=json.loads(r[4]) if r[4] else [],
            interval_seconds=r[5], last_executed_at=r[6], last_result=r[7],
            status=r[8], created_at=r[9],
        )
        for r in rows
    ]


@router.get("/schedules/{task_id}")
async def get_schedule(task_id: str) -> ScheduleResponse:
    db = await get_db()
    async with db.execute(
        "SELECT t.id, t.agent_id, a.name, t.prompt, t.allowed_tools, "
        "t.interval_seconds, t.last_executed_at, t.last_result, t.status, t.created_at "
        "FROM agentic_tasks t "
        "LEFT JOIN agents a ON a.id = t.agent_id "
        "WHERE t.id = ?",
        (task_id,),
    ) as cur:
        r = await cur.fetchone()
    if not r:
        raise HTTPException(status_code=404, detail="Schedule not found")

    return ScheduleResponse(
        id=r[0], agent_id=r[1], agent_name=r[2] or "Unknown",
        prompt=r[3], allowed_tools=json.loads(r[4]) if r[4] else [],
        interval_seconds=r[5], last_executed_at=r[6], last_result=r[7],
        status=r[8], created_at=r[9],
    )


@router.post("/schedules/{task_id}/pause")
async def pause_schedule(task_id: str):
    db = await get_db()
    async with db.execute(
        "SELECT id FROM agentic_tasks WHERE id = ?", (task_id,),
    ) as cur:
        if not await cur.fetchone():
            raise HTTPException(status_code=404, detail="Schedule not found")
    await db.execute(
        "UPDATE agentic_tasks SET status = 'paused' WHERE id = ?", (task_id,),
    )
    await db.commit()
    return {"status": "ok", "task_id": task_id}


@router.post("/schedules/{task_id}/resume")
async def resume_schedule(task_id: str):
    db = await get_db()
    async with db.execute(
        "SELECT id FROM agentic_tasks WHERE id = ?", (task_id,),
    ) as cur:
        if not await cur.fetchone():
            raise HTTPException(status_code=404, detail="Schedule not found")
    await db.execute(
        "UPDATE agentic_tasks SET status = 'active' WHERE id = ?", (task_id,),
    )
    await db.commit()
    return {"status": "ok", "task_id": task_id}


@router.put("/schedules/{task_id}")
async def update_schedule(task_id: str, request: Request):
    db = await get_db()
    async with db.execute(
        "SELECT id FROM agentic_tasks WHERE id = ?", (task_id,),
    ) as cur:
        if not await cur.fetchone():
            raise HTTPException(status_code=404, detail="Schedule not found")

    body = await request.json()
    updates = []
    params = []
    for field in ("prompt", "agent_id", "allowed_tools", "interval_seconds"):
        if field in body:
            value = body[field]
            if field == "allowed_tools":
                value = json.dumps(value)
            updates.append(f"{field} = ?")
            params.append(value)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    params.append(task_id)
    await db.execute(
        f"UPDATE agentic_tasks SET {', '.join(updates)} WHERE id = ?",
        tuple(params),
    )
    await db.commit()
    return await get_schedule(task_id)


@router.delete("/schedules/{task_id}")
async def delete_schedule(task_id: str):
    db = await get_db()
    async with db.execute(
        "SELECT id FROM agentic_tasks WHERE id = ?", (task_id,),
    ) as cur:
        if not await cur.fetchone():
            raise HTTPException(status_code=404, detail="Schedule not found")
    await db.execute("DELETE FROM agentic_tasks WHERE id = ?", (task_id,))
    await db.commit()
    return {"status": "ok", "task_id": task_id}


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
    graceful = False

    async with _workers_lock:
        worker = _active_workers.get(agent_id)
        if worker:
            worker.shutting_down = True

    if worker:
        # Try graceful shutdown (outside lock — involves long wait)
        try:
            input_path = worker.host_dir / "input.json"
            shutdown_payload = json.dumps(
                [{"type": "system_command", "command": "shutdown"}]
            )
            atomic_write(input_path, shutdown_payload.encode())
            await asyncio.wait_for(worker.process.wait(), timeout=30)
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
    async with _workers_lock:
        w = _active_workers.pop(agent_id, None)
        if w:
            old_polling = w.polling_task
            old_monitor = w.monitor_task
            w.polling_task = None
            w.monitor_task = None
    if w:
        await _cancel_task(old_polling)
        await _cancel_task(old_monitor)
        if w.mcp_manager:
            await w.mcp_manager.stop()

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
        "WHERE s.agent_id = ? AND m.visibility = 'visible' "
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


@router.patch("/agents/{agent_id}/messages")
async def hide_agent_messages(agent_id: str):
    """Mark all visible messages for an agent as hidden (used by Clear Context)."""
    db = await get_db()
    await db.execute(
        "UPDATE messages SET visibility = 'hidden' "
        "WHERE visibility = 'visible' AND session_id IN "
        "(SELECT id FROM sessions WHERE agent_id = ?)",
        (agent_id,),
    )
    await db.commit()
    return {"status": "ok"}


@router.get("/agents/{agent_id}/messages/older")
async def get_older_session_messages(agent_id: str, before: str | None = None):
    """Return all messages from the next older session with hidden messages.

    Paginated by session: each call returns one full session's worth of messages.
    Pass ``before`` (ISO timestamp of the oldest currently-loaded message) to
    page backwards through history.
    """
    db = await get_db()

    if before:
        # Find the most recent session with hidden messages older than the cursor
        async with db.execute(
            "SELECT DISTINCT s.id, s.created_at FROM sessions s "
            "JOIN messages m ON m.session_id = s.id "
            "WHERE s.agent_id = ? AND s.created_at < ? AND m.visibility = 'hidden' "
            "ORDER BY s.created_at DESC LIMIT 1",
            (agent_id, before),
        ) as cur:
            session_row = await cur.fetchone()
    else:
        # No cursor — find the most recent session with hidden messages
        async with db.execute(
            "SELECT DISTINCT s.id, s.created_at FROM sessions s "
            "JOIN messages m ON m.session_id = s.id "
            "WHERE s.agent_id = ? AND m.visibility = 'hidden' "
            "ORDER BY s.created_at DESC LIMIT 1",
            (agent_id,),
        ) as cur:
            session_row = await cur.fetchone()

    if not session_row:
        return {"messages": [], "session_id": None, "has_more": False}

    target_session_id = session_row[0]
    target_created_at = session_row[1]

    # Fetch all hidden messages from this session
    async with db.execute(
        "SELECT m.id, m.role, m.content, m.created_at, m.metadata, m.status "
        "FROM messages m "
        "WHERE m.session_id = ? AND m.visibility = 'hidden' "
        "ORDER BY m.created_at",
        (target_session_id,),
    ) as cur:
        rows = await cur.fetchall()

    messages = [
        {
            "id": r[0], "role": r[1], "content": r[2],
            "created_at": r[3], "metadata": r[4], "status": r[5],
        }
        for r in rows
    ]

    # Check if there are even older sessions with hidden messages
    async with db.execute(
        "SELECT 1 FROM sessions s "
        "JOIN messages m ON m.session_id = s.id "
        "WHERE s.agent_id = ? AND s.created_at < ? AND m.visibility = 'hidden' "
        "LIMIT 1",
        (agent_id, target_created_at),
    ) as cur:
        has_more = await cur.fetchone() is not None

    return {"messages": messages, "session_id": target_session_id, "has_more": has_more}


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


async def _get_or_create_session(agent_id: str) -> str:
    """Reuse the most recent session for this agent, or create one."""
    db = await get_db()
    async with db.execute(
        "SELECT id FROM sessions WHERE agent_id = ? ORDER BY created_at DESC LIMIT 1",
        (agent_id,),
    ) as cur:
        row = await cur.fetchone()
    if row:
        session_id = row[0]
        # Re-activate if it was marked disconnected
        await db.execute(
            "UPDATE sessions SET status = 'active', ended_at = NULL WHERE id = ?",
            (session_id,),
        )
        await db.commit()
        return session_id
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
    async with _workers_lock:
        worker = _active_workers.get(agent_id)
    if worker:
        await worker.ws_manager.send(status.model_dump_json())
    else:
        await ws.send_text(status.model_dump_json())


async def _ensure_worker(
    agent_id: str, session_id: str, ws: WebSocket
) -> None:
    # Phase 1: Grab old tasks under lock, detach them from worker
    old_polling = None
    old_monitor = None
    reattach = False

    async with _workers_lock:
        worker = _active_workers.get(agent_id)
        if worker:
            reattach = True
            old_polling = worker.polling_task
            old_monitor = worker.monitor_task
            worker.polling_task = None
            worker.monitor_task = None

    if reattach:
        # Phase 2: Cancel old tasks outside lock (monitor acquires lock)
        await _cancel_task(old_polling)
        await _cancel_task(old_monitor)

        # Phase 3: Re-acquire lock, verify worker still exists, create new tasks
        async with _workers_lock:
            worker = _active_workers.get(agent_id)
            if not worker:
                # Worker was cleaned up while we released the lock — fall through
                # to spawn path below
                reattach = False
            else:
                worker.session_id = session_id
                worker.ws_manager.attach(ws, session_id)
                worker.polling_task = start_polling_loop(
                    session_id, worker.host_dir, worker.ws_manager,
                    worker.mcp_manager,
                )
                worker.monitor_task = asyncio.create_task(
                    _monitor_worker(agent_id), name=f"monitor-{agent_id[:8]}",
                )

        if reattach:
            # Mark as running again (was idle)
            db = await get_db()
            await db.execute(
                "UPDATE agent_containers SET status = 'running', session_id = ? "
                "WHERE id = ?",
                (session_id, worker.container_record_id),
            )
            await db.commit()
            return

    # Spawn new container (no lock needed during spawn — it's a long operation)
    record_id, process, host_dir = await spawn_container(agent_id, session_id)
    mcp_mgr = await _start_mcp_manager(host_dir, agent_id)
    ws_mgr = WebSocketManager(session_id)
    ws_mgr.attach(ws, session_id)

    async with _workers_lock:
        worker = WorkerState(
            container_record_id=record_id,
            process=process,
            host_dir=host_dir,
            session_id=session_id,
            ws_manager=ws_mgr,
            mcp_manager=mcp_mgr,
            polling_task=start_polling_loop(session_id, host_dir, ws_mgr, mcp_mgr),
        )
        _active_workers[agent_id] = worker
        worker.monitor_task = asyncio.create_task(
            _monitor_worker(agent_id), name=f"monitor-{agent_id[:8]}",
        )


async def _cleanup_session(agent_id: str, session_id: str) -> None:
    """Detach WebSocket resources on disconnect. Container keeps running."""
    old_polling = None
    old_monitor = None
    container_record_id = None

    async with _workers_lock:
        worker = _active_workers.get(agent_id)
        if worker and worker.session_id == session_id:
            old_polling = worker.polling_task
            old_monitor = worker.monitor_task
            worker.polling_task = None
            worker.monitor_task = None
            worker.ws_manager.detach()
            container_record_id = worker.container_record_id

    # Cancel outside lock (monitor acquires lock)
    await _cancel_task(old_polling)
    await _cancel_task(old_monitor)

    if container_record_id:
        # Mark container as idle — reaper will kill after timeout
        db = await get_db()
        await db.execute(
            "UPDATE agent_containers SET status = 'idle' WHERE id = ?",
            (container_record_id,),
        )
        await db.commit()

    _rate_limits.pop(session_id, None)


async def ensure_worker_headless(agent_id: str, session_id: str) -> None:
    """Ensure a worker container is running for an agent, without a WebSocket.

    Used by the scheduler to guarantee the polling loop is active before
    queuing a scheduled task message.
    """
    async with _workers_lock:
        worker = _active_workers.get(agent_id)
        if worker:
            if worker.polling_task is None or worker.polling_task.done():
                worker.polling_task = start_polling_loop(
                    session_id, worker.host_dir, worker.ws_manager,
                )
            return

    record_id, process, host_dir = await spawn_container(agent_id, session_id)
    mcp_mgr = await _start_mcp_manager(host_dir, agent_id)
    ws_mgr = WebSocketManager(session_id)

    async with _workers_lock:
        worker = WorkerState(
            container_record_id=record_id,
            process=process,
            host_dir=host_dir,
            session_id=session_id,
            ws_manager=ws_mgr,
            mcp_manager=mcp_mgr,
            polling_task=start_polling_loop(session_id, host_dir, ws_mgr, mcp_mgr),
        )
        _active_workers[agent_id] = worker
        worker.monitor_task = asyncio.create_task(
            _monitor_worker(agent_id), name=f"monitor-{agent_id[:8]}",
        )


async def _respawn_worker(agent_id: str) -> None:
    """Respawn a crashed worker container for the same agent.

    Caller must hold _workers_lock or guarantee exclusive access.
    """
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
        # Restart MCP servers on the host
        if worker.mcp_manager:
            await worker.mcp_manager.stop()
        mcp_mgr = await _start_mcp_manager(host_dir, agent_id)

        # Re-queue any IN-FLIGHT messages so the new worker picks them up
        db = await get_db()
        await db.execute(
            "UPDATE message_queue SET status = 'QUEUED', flushed_at = NULL "
            "WHERE session_id = ? AND status = 'IN-FLIGHT'",
            (worker.session_id,),
        )
        await db.commit()

        async with _workers_lock:
            # Verify worker still exists (could have been cleaned up)
            if _active_workers.get(agent_id) is not worker:
                # Worker was replaced/removed — kill the container we just spawned
                container_name = f"rhclaw-{agent_id[:8]}"
                await kill_container(container_name)
                if mcp_mgr:
                    await mcp_mgr.stop()
                return
            worker.container_record_id = record_id
            worker.process = process
            worker.host_dir = host_dir
            worker.mcp_manager = mcp_mgr
            worker.polling_task = start_polling_loop(
                worker.session_id, host_dir, worker.ws_manager, mcp_mgr,
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
        async with _workers_lock:
            _active_workers.pop(agent_id, None)


async def _monitor_worker(agent_id: str) -> None:
    """Await worker process exit and handle crash recovery."""
    worker = _active_workers.get(agent_id)
    if not worker:
        return

    returncode = await worker.process.wait()

    # All post-wait logic under lock to prevent races with _ensure_worker,
    # _cleanup_session, kill_session, etc.
    async with _workers_lock:
        # Process exited — check if we still own this agent
        current = _active_workers.get(agent_id)
        if current is not worker:
            return  # Worker was replaced (e.g., by _ensure_worker)

        # Clean shutdown initiated by reaper or admin kill — skip crash recovery
        if worker.shutting_down:
            logger.info(
                "Worker for agent %s shut down cleanly (code %s)",
                agent_id, returncode,
            )
            return  # Reaper/admin kill handles cleanup

        logger.warning(
            "Worker for agent %s exited with code %s", agent_id, returncode,
        )

        # Cancel polling loop (safe under lock — polling loop doesn't acquire it)
        await _cancel_task(worker.polling_task)
        worker.polling_task = None

    # Clean up dead container (outside lock — involves subprocess)
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
        async with _workers_lock:
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
        async with _workers_lock:
            _active_workers.pop(agent_id, None)
        return

    # Respawn (acquires lock internally)
    await _respawn_worker(agent_id)


def get_active_workers() -> dict[str, WorkerState]:
    """Expose active workers for scheduler and shutdown coordination.

    Callers must hold _workers_lock when reading or mutating the returned dict.
    """
    return _active_workers


def get_workers_lock() -> asyncio.Lock:
    """Expose the workers lock for cross-module synchronization."""
    return _workers_lock


async def graceful_shutdown(timeout: int = 30) -> None:
    """Gracefully shut down all active workers before orchestrator exit.

    1. Send shutdown command to every active worker via input.json.
    2. Wait up to `timeout` seconds for all processes to exit.
    3. Force-kill any remaining containers.
    4. Await task cancellation and clean up in-memory tracking.
    """
    async with _workers_lock:
        if not _active_workers:
            return

        logger.info("Graceful shutdown: %d active workers", len(_active_workers))
        workers = list(_active_workers.items())

        # Mark all as shutting down
        for _, worker in workers:
            worker.shutting_down = True

    # Send shutdown command to all workers (outside lock — involves I/O)
    for agent_id, worker in workers:
        try:
            input_path = worker.host_dir / "input.json"
            payload = json.dumps([{"type": "system_command", "command": "shutdown"}])
            atomic_write(input_path, payload.encode())
        except Exception:
            logger.exception("Failed to send shutdown to agent %s", agent_id)

    # Wait for all processes to exit
    processes = [w.process.wait() for _, w in workers]
    try:
        await asyncio.wait_for(
            asyncio.gather(*processes, return_exceptions=True),
            timeout=timeout,
        )
        logger.info("All workers exited gracefully")
    except asyncio.TimeoutError:
        logger.warning(
            "Shutdown timeout (%ds), force-killing remaining workers", timeout,
        )
        for agent_id, worker in workers:
            if worker.process.returncode is None:
                container_name = f"rhclaw-{agent_id[:8]}"
                await kill_container(container_name)

    # Cancel tasks, stop MCP servers, and finalize DB state
    for _, worker in workers:
        await _cancel_task(worker.polling_task)
        await _cancel_task(worker.monitor_task)
        if worker.mcp_manager:
            await worker.mcp_manager.stop()

    db = await get_db()
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    for _, worker in workers:
        await db.execute(
            "UPDATE agent_containers SET status = 'stopped', stopped_at = ? "
            "WHERE id = ?",
            (now, worker.container_record_id),
        )
    await db.commit()

    async with _workers_lock:
        _active_workers.clear()
    logger.info("Graceful shutdown complete")


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

    session_id = await _get_or_create_session(agent_id)

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
            async with _workers_lock:
                worker = _active_workers.get(agent_id)
                container_record_id = worker.container_record_id if worker else None
            if container_record_id:
                now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                db = await get_db()
                await db.execute(
                    "UPDATE agent_containers SET last_activity = ? WHERE id = ?",
                    (now, container_record_id),
                )
                await db.commit()

            await _send_queue_status(ws, session_id, agent_id)
            await _ensure_worker(agent_id, session_id, ws)

    except WebSocketDisconnect:
        await _cleanup_session(agent_id, session_id)
