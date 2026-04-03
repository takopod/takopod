"""Boot recovery: reconcile stale state after an orchestrator restart."""

import asyncio
import logging
import time
from pathlib import Path

from orchestrator.container_manager import AGENTS_DIR, PODMAN
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

    await db.commit()

    logger.info(
        "Boot recovery complete: %d containers killed, %d messages re-queued, "
        "%d IPC files cleaned, %d container statuses reset",
        killed, requeued, files_cleaned, statuses_reset,
    )
