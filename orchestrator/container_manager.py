import asyncio
import json
import logging
import os
import shutil
import uuid
from pathlib import Path

from orchestrator.db import get_db

logger = logging.getLogger(__name__)

PODMAN = "/opt/podman/bin/podman"
NETWORK = "rhclaw-internal"
IMAGE = "rhclaw-worker"
AGENTS_DIR = Path("data/agents")
MCP_CONFIGS_DIR = Path("data/mcp-configs")
TEMPLATES_DIR = Path("agent_templates")


async def _run(cmd: list[str], check: bool = True) -> asyncio.subprocess.Process:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if check and proc.returncode != 0:
        raise RuntimeError(
            f"Command failed: {' '.join(cmd)}\n"
            f"stderr: {stderr.decode().strip()}"
        )
    return proc


async def ensure_network() -> None:
    proc = await asyncio.create_subprocess_exec(
        PODMAN, "network", "exists", NETWORK,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.wait()
    if proc.returncode != 0:
        await _run([PODMAN, "network", "create", NETWORK])
        logger.info("Created podman network: %s", NETWORK)


async def build_image() -> None:
    logger.info("Building worker image: %s", IMAGE)
    await _run([
        PODMAN, "build", "-t", IMAGE, "-f", "worker/Containerfile", "worker/",
    ])
    logger.info("Worker image built: %s", IMAGE)


def create_agent_workspace(
    agent_id: str,
    agent_type: str,
    agent_name: str | None = None,
    claude_md: str | None = None,
    soul_md: str | None = None,
    memory_md: str | None = None,
    mcp_config: dict | None = None,
) -> Path:
    host_dir = (AGENTS_DIR / agent_id).resolve()
    host_dir.mkdir(parents=True, exist_ok=True)
    (host_dir / "sessions").mkdir(exist_ok=True)
    (host_dir / "memory").mkdir(exist_ok=True)
    (host_dir / "config").mkdir(exist_ok=True)

    template_dir = TEMPLATES_DIR / agent_type
    if not template_dir.is_dir():
        template_dir = TEMPLATES_DIR / "default"

    for filename in ("CLAUDE.md", "SOUL.md", "MEMORY.md"):
        content = None
        if filename == "CLAUDE.md" and claude_md:
            content = claude_md
        elif filename == "SOUL.md" and soul_md:
            content = soul_md
        elif filename == "MEMORY.md" and memory_md:
            content = memory_md

        target = host_dir / filename
        if not content and (template_dir / filename).is_file():
            content = (template_dir / filename).read_text()

        # Prepend agent identity to MEMORY.md
        if filename == "MEMORY.md" and agent_name and content:
            identity = f"Your name is {agent_name}.\n\n"
            content = identity + content
        elif filename == "MEMORY.md" and agent_name and not content:
            content = f"Your name is {agent_name}.\n"

        if content:
            target.write_text(content)

    # Copy skills: common first, then template-specific (can override)
    dest_skills = host_dir / ".claude" / "skills"
    common_skills = Path("skills")
    if common_skills.is_dir():
        dest_skills.mkdir(parents=True, exist_ok=True)
        shutil.copytree(common_skills, dest_skills, dirs_exist_ok=True)
    template_skills = template_dir / ".claude" / "skills"
    if template_skills.is_dir():
        dest_skills.mkdir(parents=True, exist_ok=True)
        shutil.copytree(template_skills, dest_skills, dirs_exist_ok=True)

    # MCP server configuration (stored outside workspace so containers can't read secrets)
    mcp_path = MCP_CONFIGS_DIR / f"{agent_id}.json"
    MCP_CONFIGS_DIR.mkdir(parents=True, exist_ok=True)
    if mcp_config:
        mcp_path.write_text(json.dumps(mcp_config, indent=2))
    elif (template_dir / ".mcp.json").is_file():
        shutil.copy2(template_dir / ".mcp.json", mcp_path)

    return host_dir


async def write_agents_json(agent_id: str, host_dir: Path) -> None:
    db = await get_db()
    async with db.execute(
        "SELECT name, agent_type FROM agents WHERE id != ? AND status = 'active'",
        (agent_id,),
    ) as cur:
        rows = await cur.fetchall()

    agents = [{"name": row[0], "agent_type": row[1]} for row in rows]
    manifest_path = host_dir / "agents.json"
    manifest_path.write_text(json.dumps(agents, indent=2))


async def spawn_container(
    agent_id: str, session_id: str
) -> tuple[str, asyncio.subprocess.Process, Path]:
    db = await get_db()
    async with db.execute(
        "SELECT host_dir, container_memory, container_cpus FROM agents WHERE id = ?",
        (agent_id,),
    ) as cur:
        row = await cur.fetchone()
    if not row:
        raise ValueError(f"Agent {agent_id} not found")

    host_dir = Path(row[0])
    container_memory = row[1]
    container_cpus = row[2]

    # Read settings for worker env vars
    async with db.execute(
        "SELECT value FROM settings WHERE key = 'ollama_enabled'"
    ) as cur:
        setting_row = await cur.fetchone()
    ollama_enabled = setting_row[0] if setting_row else "true"

    host_dir.mkdir(parents=True, exist_ok=True)
    await write_agents_json(agent_id, host_dir)

    record_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO agent_containers "
        "(id, agent_id, session_id, container_type, status) "
        "VALUES (?, ?, ?, 'session', 'starting')",
        (record_id, agent_id, session_id),
    )
    await db.commit()

    container_name = f"rhclaw-{agent_id[:8]}"

    # Kill any orphaned container with the same name (e.g., left over
    # after an orchestrator restart / uvicorn --reload).
    await _run([PODMAN, "rm", "-f", container_name], check=False)

    cmd = [
        PODMAN, "run",
        "--name", container_name,
        "--network", NETWORK,
        "--label", "rhclaw.managed=true",
        "--label", f"rhclaw.agent_id={agent_id}",
        "--label", f"rhclaw.session_id={session_id}",
        "--memory", container_memory,
        "--cpus", container_cpus,
        "--pids-limit", "256",
        "--tmpfs", "/tmp:rw,size=512m",
        "--tmpfs", "/var/tmp:rw,size=64m",
        "-v", f"{host_dir}:/workspace:Z",
        "-v", f"{Path.home() / '.config/gcloud'}:/root/.config/gcloud:ro,Z",
        "-e", "CLAUDE_CODE_USE_VERTEX=1",
        "-e", f"CLOUD_ML_REGION={os.environ.get('GOOGLE_CLOUD_REGION', '')}",
        "-e", f"ANTHROPIC_VERTEX_PROJECT_ID={os.environ.get('GOOGLE_CLOUD_PROJECT', '')}",
        "-e", f"OLLAMA_ENABLED={ollama_enabled}",
        IMAGE,
    ]

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )

    await db.execute(
        "UPDATE agent_containers SET status = 'running', pid = ? WHERE id = ?",
        (process.pid, record_id),
    )
    await db.commit()
    logger.info(
        "Spawned container %s for agent %s session %s (pid=%d)",
        container_name, agent_id, session_id, process.pid,
    )

    return record_id, process, host_dir


async def spawn_scheduled_container(
    agent_id: str, task_id: str
) -> tuple[str, asyncio.subprocess.Process, Path]:
    """Spawn an ephemeral container for a scheduled task (e.g., memory compaction).

    Similar to spawn_container() but with container_type='scheduled_task',
    no session_id, Ollama disabled, and a distinct container name to avoid
    collision with session containers.
    """
    db = await get_db()
    async with db.execute(
        "SELECT host_dir, container_memory, container_cpus FROM agents WHERE id = ?",
        (agent_id,),
    ) as cur:
        row = await cur.fetchone()
    if not row:
        raise ValueError(f"Agent {agent_id} not found")

    host_dir = Path(row[0])
    container_memory = row[1]
    container_cpus = row[2]

    host_dir.mkdir(parents=True, exist_ok=True)

    record_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO agent_containers "
        "(id, agent_id, session_id, container_type, status) "
        "VALUES (?, ?, NULL, 'scheduled_task', 'starting')",
        (record_id, agent_id),
    )
    await db.commit()

    container_name = f"rhclaw-task-{agent_id[:8]}"
    await _run([PODMAN, "rm", "-f", container_name], check=False)

    cmd = [
        PODMAN, "run",
        "--name", container_name,
        "--network", NETWORK,
        "--label", "rhclaw.managed=true",
        "--label", f"rhclaw.agent_id={agent_id}",
        "--label", f"rhclaw.task_id={task_id}",
        "--memory", container_memory,
        "--cpus", container_cpus,
        "--pids-limit", "256",
        "--tmpfs", "/tmp:rw,size=512m",
        "--tmpfs", "/var/tmp:rw,size=64m",
        "-v", f"{host_dir}:/workspace:Z",
        "-v", f"{Path.home() / '.config/gcloud'}:/root/.config/gcloud:ro,Z",
        "-e", "CLAUDE_CODE_USE_VERTEX=1",
        "-e", f"CLOUD_ML_REGION={os.environ.get('GOOGLE_CLOUD_REGION', '')}",
        "-e", f"ANTHROPIC_VERTEX_PROJECT_ID={os.environ.get('GOOGLE_CLOUD_PROJECT', '')}",
        "-e", "OLLAMA_ENABLED=false",
        IMAGE,
    ]

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )

    await db.execute(
        "UPDATE agent_containers SET status = 'running', pid = ? WHERE id = ?",
        (process.pid, record_id),
    )
    await db.commit()
    logger.info(
        "Spawned scheduled task container %s for agent %s task %s (pid=%d)",
        container_name, agent_id, task_id, process.pid,
    )

    return record_id, process, host_dir


async def stop_container(container_name: str) -> None:
    await _run([PODMAN, "stop", container_name], check=False)
    await _run([PODMAN, "rm", "-f", container_name], check=False)


async def kill_container(container_name: str) -> None:
    await _run([PODMAN, "kill", container_name], check=False)
    await _run([PODMAN, "rm", "-f", container_name], check=False)
