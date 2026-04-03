import asyncio
import logging
import uuid
from pathlib import Path

from orchestrator.db import get_db

logger = logging.getLogger(__name__)

PODMAN = "/opt/podman/bin/podman"
NETWORK = "rhclaw-internal"
IMAGE = "rhclaw-worker"
DATA_DIR = Path("data/sessions")


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


async def spawn_container(
    session_id: str, agent_type: str = "stub"
) -> tuple[str, asyncio.subprocess.Process, Path]:
    host_dir = (DATA_DIR / session_id).resolve()
    host_dir.mkdir(parents=True, exist_ok=True)

    record_id = str(uuid.uuid4())
    db = await get_db()
    await db.execute(
        "INSERT INTO agent_containers "
        "(id, session_id, agent_type, container_type, host_dir, status) "
        "VALUES (?, ?, ?, 'session', ?, 'starting')",
        (record_id, session_id, agent_type, str(host_dir)),
    )
    await db.commit()

    container_name = f"rhclaw-{session_id[:8]}"
    cmd = [
        PODMAN, "run", "--rm",
        "--name", container_name,
        "--network", NETWORK,
        "--read-only",
        "--label", "rhclaw.managed=true",
        "--label", f"rhclaw.session_id={session_id}",
        "--memory", "2g",
        "--cpus", "2",
        "--pids-limit", "256",
        "--tmpfs", "/tmp:rw,size=512m",
        "--tmpfs", "/var/tmp:rw,size=64m",
        "-v", f"{host_dir}:/workspace:Z",
        IMAGE,
    ]

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    await db.execute(
        "UPDATE agent_containers SET status = 'running', pid = ? WHERE id = ?",
        (process.pid, record_id),
    )
    await db.commit()
    logger.info(
        "Spawned container %s for session %s (pid=%d)",
        container_name, session_id, process.pid,
    )

    return record_id, process, host_dir


async def stop_container(container_name: str) -> None:
    await _run([PODMAN, "stop", container_name], check=False)
    await _run([PODMAN, "rm", "-f", container_name], check=False)


async def kill_container(container_name: str) -> None:
    await _run([PODMAN, "kill", container_name], check=False)
    await _run([PODMAN, "rm", "-f", container_name], check=False)
