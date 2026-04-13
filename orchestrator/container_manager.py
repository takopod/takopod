import asyncio
import json
import logging
import os
import re
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


def slugify(name: str) -> str:
    """Convert a display name to a filesystem-safe slug."""
    slug = name.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug or "agent"


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
) -> Path:
    slug = slugify(agent_name) if agent_name else agent_id
    host_dir = (AGENTS_DIR / slug).resolve()
    host_dir.mkdir(parents=True, exist_ok=True)
    (host_dir / "memory").mkdir(exist_ok=True)
    (host_dir / "config").mkdir(exist_ok=True)

    template_dir = TEMPLATES_DIR / agent_type
    if not template_dir.is_dir():
        template_dir = TEMPLATES_DIR / "default"

    for filename in ("CLAUDE.md", "SOUL.md", "MEMORY.md"):
        content = None
        target = host_dir / filename
        if (template_dir / filename).is_file():
            content = (template_dir / filename).read_text()

        # Prepend agent identity to MEMORY.md
        if filename == "MEMORY.md" and agent_name and content:
            identity = f"Your name is {agent_name}.\n\n"
            content = identity + content
        elif filename == "MEMORY.md" and agent_name and not content:
            content = f"Your name is {agent_name}.\n"

        if content:
            target.write_text(content)

    # Skills are synced separately via sync_agent_skills() after DB rows are created.
    # Template-specific skills are still copied here as overrides.
    dest_skills = host_dir / ".claude" / "skills"
    template_skills = template_dir / ".claude" / "skills"
    if template_skills.is_dir():
        dest_skills.mkdir(parents=True, exist_ok=True)
        shutil.copytree(template_skills, dest_skills, dirs_exist_ok=True)

    # MCP servers are now configured globally and toggled per-agent.
    # No per-agent MCP config file is created at workspace setup.

    return host_dir


BUILTIN_SKILLS_DIR = Path("skills")
USER_SKILLS_DIR = Path("data/skills")
REGISTRY_MANIFEST = ".registry.json"


def _scan_skills_dir(sdir: Path) -> list[str]:
    """Scan a skills directory and return skill IDs found."""
    if not sdir.is_dir():
        return []
    ids: list[str] = []
    for item in sorted(sdir.iterdir()):
        if item.is_file() and item.suffix == ".md":
            ids.append(item.stem)
        elif item.is_dir() and (item / "SKILL.md").is_file():
            ids.append(item.name)
    return ids


def _list_registry_skill_ids() -> list[str]:
    """Scan both user and builtin skill directories and return all skill IDs.

    User skills (data/skills/) take precedence over builtin skills (skills/).
    """
    seen: set[str] = set()
    ids: list[str] = []
    for skill_id in _scan_skills_dir(USER_SKILLS_DIR) + _scan_skills_dir(BUILTIN_SKILLS_DIR):
        if skill_id not in seen:
            seen.add(skill_id)
            ids.append(skill_id)
    return ids


def _find_skill_source(skill_id: str) -> Path | None:
    """Find which directory a skill lives in (user override first, then builtin)."""
    for sdir in (USER_SKILLS_DIR, BUILTIN_SKILLS_DIR):
        dir_path = sdir / skill_id
        flat_path = sdir / f"{skill_id}.md"
        if dir_path.is_dir() and (dir_path / "SKILL.md").is_file():
            return sdir
        if flat_path.is_file():
            return sdir
    return None


def _copy_system_skill(skill_id: str, dest_skills: Path) -> None:
    """Copy a single system skill into an agent's .claude/skills/ directory."""
    sdir = _find_skill_source(skill_id)
    if not sdir:
        return

    flat_path = sdir / f"{skill_id}.md"
    dir_path = sdir / skill_id

    target = dest_skills / skill_id
    target.mkdir(parents=True, exist_ok=True)

    if dir_path.is_dir() and (dir_path / "SKILL.md").is_file():
        shutil.copytree(dir_path, target, dirs_exist_ok=True)
    elif flat_path.is_file():
        shutil.copy2(flat_path, target / "SKILL.md")


async def seed_agent_skills(agent_id: str) -> None:
    """Insert agent_skills rows for all system skills (called on agent creation)."""
    db = await get_db()
    skill_ids = _list_registry_skill_ids()
    for skill_id in skill_ids:
        await db.execute(
            "INSERT OR IGNORE INTO agent_skills (agent_id, skill_id, enabled) "
            "VALUES (?, ?, 1)",
            (agent_id, skill_id),
        )
    await db.commit()


async def sync_agent_skills(agent_id: str, host_dir: Path) -> None:
    """Sync registry skills into an agent's workspace based on enabled flags.

    - Reads enabled skill IDs from agent_skills table
    - Removes registry skills that are disabled or no longer in the registry
    - Copies enabled registry skills from skills/ into .claude/skills/
    - Preserves custom (non-registry) agent skills
    """
    db = await get_db()
    dest_skills = host_dir / ".claude" / "skills"
    dest_skills.mkdir(parents=True, exist_ok=True)

    # Get enabled skill IDs from DB
    async with db.execute(
        "SELECT skill_id FROM agent_skills WHERE agent_id = ? AND enabled = 1",
        (agent_id,),
    ) as cur:
        rows = await cur.fetchall()
    enabled_ids = {row[0] for row in rows}

    # Builtin skills are always enabled regardless of DB state
    enabled_ids.update(_scan_skills_dir(BUILTIN_SKILLS_DIR))

    # Read current registry manifest (tracks which skills in workspace came from registry)
    manifest_path = dest_skills / REGISTRY_MANIFEST
    previous_registry: set[str] = set()
    if manifest_path.is_file():
        try:
            previous_registry = set(json.loads(manifest_path.read_text()))
        except (json.JSONDecodeError, OSError):
            pass

    # Remove registry skills that are no longer enabled
    for skill_id in previous_registry - enabled_ids:
        skill_dir = dest_skills / skill_id
        if skill_dir.is_dir():
            shutil.rmtree(skill_dir)
            logger.debug("Removed disabled registry skill %s for agent %s", skill_id, agent_id)

    # Copy/update enabled registry skills
    for skill_id in enabled_ids:
        _copy_system_skill(skill_id, dest_skills)

    # Write updated manifest
    manifest_path.write_text(json.dumps(sorted(enabled_ids)))
    logger.debug("Synced %d registry skills for agent %s", len(enabled_ids), agent_id)


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
    agent_id: str,
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
        "(id, agent_id, container_type, status) "
        "VALUES (?, ?, 'session', 'starting')",
        (record_id, agent_id),
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
        "Spawned container %s for agent %s (pid=%d)",
        container_name, agent_id, process.pid,
    )

    return record_id, process, host_dir


async def spawn_scheduled_container(
    agent_id: str, task_id: str
) -> tuple[str, asyncio.subprocess.Process, Path]:
    """Spawn an ephemeral container for a scheduled task (e.g., memory compaction).

    Similar to spawn_container() but with container_type='scheduled_task',
    Ollama disabled, and a distinct container name to avoid collision with
    session containers.
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
        "(id, agent_id, container_type, status) "
        "VALUES (?, ?, 'scheduled_task', 'starting')",
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
