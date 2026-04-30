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

PODMAN = shutil.which("podman") or "/opt/podman/bin/podman"
NETWORK = "takopod-internal"
IMAGE = "takopod-worker"
AGENTS_DIR = Path("data/agents")
SEED_DIR = Path("agent_templates/default")


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


def _claude_auth_args() -> list[str]:
    """Return podman args for Claude auth.

    Prefers subscription OAuth (CLAUDE_CODE_OAUTH_TOKEN) if set, else falls
    back to Vertex AI via mounted gcloud credentials.
    """
    oauth_token = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")
    if oauth_token:
        return ["-e", f"CLAUDE_CODE_OAUTH_TOKEN={oauth_token}"]
    return [
        "-v", f"{Path.home() / '.config/gcloud'}:/root/.config/gcloud:ro,Z",
        "-e", "CLAUDE_CODE_USE_VERTEX=1",
        "-e", f"CLOUD_ML_REGION={os.environ.get('GOOGLE_CLOUD_REGION', '')}",
        "-e", f"ANTHROPIC_VERTEX_PROJECT_ID={os.environ.get('GOOGLE_CLOUD_PROJECT', '')}",
    ]


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
    agent_name: str | None = None,
) -> Path:
    slug = slugify(agent_name) if agent_name else agent_id
    host_dir = (AGENTS_DIR / slug).resolve()
    host_dir.mkdir(parents=True, exist_ok=True)
    (host_dir / "memory").mkdir(exist_ok=True)
    (host_dir / "config").mkdir(exist_ok=True)

    for filename in ("CLAUDE.md", "SOUL.md", "MEMORY.md", "BOOTSTRAP.md"):
        content = None
        target = host_dir / filename
        seed_file = SEED_DIR / filename
        if seed_file.is_file():
            content = seed_file.read_text()

        # Prepend agent identity to MEMORY.md
        if filename == "MEMORY.md" and agent_name and content:
            identity = f"Your name is {agent_name}.\n\n"
            content = identity + content
        elif filename == "MEMORY.md" and agent_name and not content:
            content = f"Your name is {agent_name}.\n"

        if content:
            target.write_text(content)

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



_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---", re.DOTALL)


def _is_always_enabled_skill(skill_id: str) -> bool:
    """Check if a skill has always_enabled: true in its frontmatter."""
    for sdir in (USER_SKILLS_DIR, BUILTIN_SKILLS_DIR):
        for path in (sdir / skill_id / "SKILL.md", sdir / f"{skill_id}.md"):
            if path.is_file():
                m = _FRONTMATTER_RE.match(path.read_text())
                if m:
                    import yaml
                    data = yaml.safe_load(m.group(1))
                    if isinstance(data, dict):
                        return bool(data.get("always_enabled", False))
                return False
    return False


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
    """Copy a single system skill into the destination skills directory."""
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
    """Seed always_enabled builtin skills into the DB for a newly created agent."""
    db = await get_db()
    for skill_id in _scan_skills_dir(BUILTIN_SKILLS_DIR):
        if not _is_always_enabled_skill(skill_id):
            continue
        await db.execute(
            "INSERT OR IGNORE INTO agent_skills (agent_id, skill_id) VALUES (?, ?)",
            (agent_id, skill_id),
        )
    await db.commit()


async def sync_agent_skills(agent_id: str, host_dir: Path) -> None:
    """Sync registry skills into an agent's .claude/skills/ directory.

    - Reads skill IDs from agent_skills table
    - Removes registry skills no longer in the registry
    - Copies active registry skills directly into .claude/skills/
    - Preserves custom (non-registry) agent skills
    """
    db = await get_db()
    dest_skills = host_dir / ".claude" / "skills"
    dest_skills.mkdir(parents=True, exist_ok=True)

    async with db.execute(
        "SELECT skill_id FROM agent_skills WHERE agent_id = ?",
        (agent_id,),
    ) as cur:
        rows = await cur.fetchall()
    active_ids = {row[0] for row in rows}

    for sid in _scan_skills_dir(BUILTIN_SKILLS_DIR):
        if _is_always_enabled_skill(sid):
            active_ids.add(sid)

    manifest_path = dest_skills / REGISTRY_MANIFEST
    previous_registry: set[str] = set()
    if manifest_path.is_file():
        try:
            previous_registry = set(json.loads(manifest_path.read_text()))
        except (json.JSONDecodeError, OSError):
            pass

    for skill_id in previous_registry - active_ids:
        skill_dir = dest_skills / skill_id
        if skill_dir.is_dir():
            shutil.rmtree(skill_dir)
            logger.debug("Removed registry skill %s for agent %s", skill_id, agent_id)

    for skill_id in active_ids:
        _copy_system_skill(skill_id, dest_skills)

    manifest_path.write_text(json.dumps(sorted(active_ids)))
    logger.debug("Synced %d registry skills for agent %s", len(active_ids), agent_id)


async def write_workspace_settings(host_dir: Path) -> None:
    """Write global settings to .settings.json in the agent workspace."""
    from orchestrator.settings import get_all_settings
    all_settings = await get_all_settings()
    workspace_settings = {
        "session_history_window_size": int(
            all_settings.get("session_history_window_size", "20")
        ),
    }
    from orchestrator.ipc import atomic_write
    settings_path = host_dir / ".settings.json"
    atomic_write(settings_path, json.dumps(workspace_settings, indent=2).encode())


async def seed_session_history(agent_id: str, host_dir: Path) -> None:
    """Write session_history.json from the orchestrator DB before container start.

    The worker loads this file on startup to restore conversation context.
    Without this, a container restarted after idle timeout would only see
    whatever the previous worker process had persisted — which may be stale
    or incomplete.
    """
    from orchestrator.ipc import atomic_write
    from orchestrator.settings import get_all_settings

    all_settings = await get_all_settings()
    window = int(all_settings.get("session_history_window_size", "20"))

    db = await get_db()
    async with db.execute(
        "SELECT role, content FROM messages "
        "WHERE agent_id = ? AND visibility = 'visible' "
        "ORDER BY created_at DESC LIMIT ?",
        (agent_id, window),
    ) as cur:
        rows = await cur.fetchall()

    if not rows:
        return

    entries = [{"role": role, "content": content} for role, content in reversed(rows)]
    history_path = host_dir / "session_history.json"
    atomic_write(history_path, json.dumps(entries).encode())
    logger.info("Seeded session_history.json with %d messages for agent %s",
                len(entries), agent_id)


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
    await write_workspace_settings(host_dir)
    await seed_session_history(agent_id, host_dir)

    record_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO agent_containers "
        "(id, agent_id, container_type, status) "
        "VALUES (?, ?, 'session', 'starting')",
        (record_id, agent_id),
    )
    await db.commit()

    container_name = f"takopod-{agent_id[:8]}"

    # Kill any orphaned container with the same name (e.g., left over
    # after an orchestrator restart / uvicorn --reload).
    await _run([PODMAN, "rm", "-f", container_name], check=False)

    cmd = [
        PODMAN, "run",
        "--name", container_name,
        "--network", NETWORK,
        "--label", "takopod.managed=true",
        "--label", f"takopod.agent_id={agent_id}",
        "--memory", container_memory,
        "--cpus", container_cpus,
        "--pids-limit", "256",
        "--tmpfs", "/tmp:rw,size=512m",
        "--tmpfs", "/var/tmp:rw,size=64m",
        "-v", f"{host_dir}:/workspace:Z",
        *_claude_auth_args(),
        "-e", f"OLLAMA_ENABLED={ollama_enabled}",
    ]

    if (host_dir / ".gitconfig").is_file():
        cmd += ["-e", "GIT_CONFIG_GLOBAL=/workspace/.gitconfig"]

    cmd.append(IMAGE)

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
    await write_workspace_settings(host_dir)

    record_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO agent_containers "
        "(id, agent_id, container_type, status) "
        "VALUES (?, ?, 'scheduled_task', 'starting')",
        (record_id, agent_id),
    )
    await db.commit()

    container_name = f"takopod-task-{agent_id[:8]}"
    await _run([PODMAN, "rm", "-f", container_name], check=False)

    cmd = [
        PODMAN, "run",
        "--name", container_name,
        "--network", NETWORK,
        "--label", "takopod.managed=true",
        "--label", f"takopod.agent_id={agent_id}",
        "--label", f"takopod.task_id={task_id}",
        "--memory", container_memory,
        "--cpus", container_cpus,
        "--pids-limit", "256",
        "--tmpfs", "/tmp:rw,size=512m",
        "--tmpfs", "/var/tmp:rw,size=64m",
        "-v", f"{host_dir}:/workspace:Z",
        *_claude_auth_args(),
        "-e", "OLLAMA_ENABLED=false",
    ]

    if (host_dir / ".gitconfig").is_file():
        cmd += ["-e", "GIT_CONFIG_GLOBAL=/workspace/.gitconfig"]

    cmd.append(IMAGE)

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
