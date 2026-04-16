"""Boot recovery: reconcile stale state after an orchestrator restart."""

import asyncio
import logging
import time
from pathlib import Path

from orchestrator.container_manager import (
    AGENTS_DIR,
    BUILTIN_SKILLS_DIR,
    PODMAN,
    _is_always_enabled_skill,
    _scan_skills_dir,
)
from orchestrator.db import get_db

logger = logging.getLogger(__name__)


async def boot_recovery() -> None:
    """Run state reconciliation before accepting connections.

    Must be called after DB migrations but before network/image setup.
    Steps follow ARCHITECTURE.md Section 1 (Orchestrator Boot Recovery).
    """
    db = await get_db()

    # Step 1: Discover all managed containers (running or stopped)
    proc = await asyncio.create_subprocess_exec(
        PODMAN, "ps", "-a",
        "--filter", "label=rhclaw.managed=true",
        "-q",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    container_ids = [
        cid.strip() for cid in stdout.decode().splitlines() if cid.strip()
    ]

    # Step 2: Force-remove all managed containers
    killed = 0
    for cid in container_ids:
        rm_proc = await asyncio.create_subprocess_exec(
            PODMAN, "rm", "-f", cid,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await rm_proc.wait()
        killed += 1

    # Step 3: Re-queue IN-FLIGHT messages as QUEUED
    cursor = await db.execute(
        "UPDATE message_queue SET status = 'QUEUED', flushed_at = NULL "
        "WHERE status = 'IN-FLIGHT'"
    )
    requeued = cursor.rowcount

    # Step 4: Delete stale IPC files
    files_cleaned = 0
    if AGENTS_DIR.is_dir():
        for ipc_file in AGENTS_DIR.glob("*/input.json"):
            ipc_file.unlink(missing_ok=True)
            files_cleaned += 1
        for ipc_file in AGENTS_DIR.glob("*/output.json"):
            ipc_file.unlink(missing_ok=True)
            files_cleaned += 1
        for ipc_file in AGENTS_DIR.glob("*/request.json"):
            ipc_file.unlink(missing_ok=True)
            files_cleaned += 1
        for ipc_file in AGENTS_DIR.glob("*/response.json"):
            ipc_file.unlink(missing_ok=True)
            files_cleaned += 1

    # Step 5: Reset stale container statuses
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    cursor = await db.execute(
        "UPDATE agent_containers SET status = 'stopped', stopped_at = ? "
        "WHERE status IN ('running', 'starting', 'stopping', 'idle')",
        (now,),
    )
    statuses_reset = cursor.rowcount

    # Step 6: Mark pending/running scheduled tasks as failed
    cursor = await db.execute(
        "UPDATE scheduled_tasks SET status = 'failed', "
        "completed_at = ?, error_message = 'orchestrator restart' "
        "WHERE status IN ('pending', 'running')",
        (now,),
    )
    tasks_failed = cursor.rowcount

    # Step 7: Seed builtin skills for all agents
    builtin_skill_ids = _scan_skills_dir(BUILTIN_SKILLS_DIR)
    async with db.execute("SELECT id FROM agents") as cur:
        agent_rows = await cur.fetchall()
    skills_seeded = 0
    for (agent_id,) in agent_rows:
        for skill_id in builtin_skill_ids:
            enabled = 1 if _is_always_enabled_skill(skill_id) else 0
            cursor = await db.execute(
                "INSERT INTO agent_skills (agent_id, skill_id, enabled) "
                "VALUES (?, ?, ?) ON CONFLICT(agent_id, skill_id) DO NOTHING",
                (agent_id, skill_id, enabled),
            )
            skills_seeded += cursor.rowcount

    await db.commit()

    logger.info(
        "Boot recovery complete: %d containers killed, %d messages re-queued, "
        "%d IPC files cleaned, %d container statuses reset, "
        "%d scheduled tasks failed, %d builtin skills seeded",
        killed, requeued, files_cleaned, statuses_reset, tasks_failed,
        skills_seeded,
    )
