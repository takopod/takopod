"""Scheduler: background task runner, timeout enforcement, and idle reaper.

Runs as a single asyncio task created in main.py lifespan. Combines three
periodic duties on a unified 10-second tick:
  1. Poll scheduled_tasks for pending work and spawn ephemeral containers.
  2. Enforce timeouts on running scheduled tasks.
  3. Reap idle worker containers (every 3rd tick = 30s, extracted from routes.py).
"""

import asyncio
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from orchestrator.container_manager import (
    kill_container,
    spawn_scheduled_container,
)
from orchestrator.db import get_db
from orchestrator.ipc import atomic_write
from orchestrator.models import SystemErrorFrame
from orchestrator.ws_manager import WS_CLOSE_IDLE_TIMEOUT

logger = logging.getLogger(__name__)

IDLE_TIMEOUT_SECONDS = int(os.environ.get("IDLE_TIMEOUT_SECONDS", "300"))
SCHEDULER_TICK = 10  # seconds between scheduler iterations
IDLE_REAPER_TICKS = 3  # run idle reaper every N ticks (30s at TICK=10)
TASK_POLL_RESPONSE_INTERVAL = 1.0  # seconds between response.json polls


@dataclass
class RunningTaskInfo:
    task_id: str
    agent_id: str
    process: asyncio.subprocess.Process
    container_record_id: str
    host_dir: Path
    started_at: float  # time.monotonic()
    timeout_seconds: int
    asyncio_task: asyncio.Task


_running_tasks: dict[str, RunningTaskInfo] = {}


# ---------------------------------------------------------------------------
# Main scheduler loop
# ---------------------------------------------------------------------------


async def run_scheduler() -> None:
    """Main background loop. Runs forever until cancelled."""
    tick = 0
    while True:
        await asyncio.sleep(SCHEDULER_TICK)
        tick += 1

        try:
            await _poll_pending_tasks()
        except Exception:
            logger.exception("Scheduler: error polling pending tasks")

        try:
            await _check_task_timeouts()
        except Exception:
            logger.exception("Scheduler: error checking task timeouts")

        if tick % IDLE_REAPER_TICKS == 0:
            try:
                await _reap_idle_workers()
            except Exception:
                logger.exception("Idle reaper error")


# ---------------------------------------------------------------------------
# Scheduled task runner
# ---------------------------------------------------------------------------


async def _poll_pending_tasks() -> None:
    """Find pending tasks ready to run and spawn containers for them."""
    db = await get_db()
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    async with db.execute(
        "SELECT id, agent_id, task_type, payload, timeout_seconds "
        "FROM scheduled_tasks "
        "WHERE status = 'pending' AND scheduled_at <= ? "
        "ORDER BY scheduled_at LIMIT 5",
        (now,),
    ) as cur:
        rows = await cur.fetchall()

    for task_id, agent_id, task_type, payload_json, timeout_seconds in rows:
        if task_id in _running_tasks:
            continue
        payload = json.loads(payload_json) if payload_json else {}
        task = asyncio.create_task(
            _run_scheduled_task(task_id, agent_id, task_type, payload, timeout_seconds),
            name=f"scheduled-task-{task_id[:8]}",
        )
        # RunningTaskInfo is populated inside _run_scheduled_task after spawn


async def _run_scheduled_task(
    task_id: str,
    agent_id: str,
    task_type: str,
    payload: dict,
    timeout_seconds: int,
) -> None:
    """Spawn an ephemeral container, deliver the task, wait for result."""
    db = await get_db()

    # Mark as running
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    await db.execute(
        "UPDATE scheduled_tasks SET status = 'running', started_at = ? WHERE id = ?",
        (now, task_id),
    )
    await db.commit()

    record_id = None
    process = None
    host_dir = None
    container_name = f"rhclaw-task-{agent_id[:8]}"

    try:
        record_id, process, host_dir = await spawn_scheduled_container(agent_id, task_id)

        # Track in-memory for timeout enforcement
        info = RunningTaskInfo(
            task_id=task_id,
            agent_id=agent_id,
            process=process,
            container_record_id=record_id,
            host_dir=host_dir,
            started_at=time.monotonic(),
            timeout_seconds=timeout_seconds,
            asyncio_task=asyncio.current_task(),
        )
        _running_tasks[task_id] = info

        # Write task input
        input_path = host_dir / "input.json"
        task_payload = json.dumps([{
            "type": "scheduled_task",
            "task_type": task_type,
            "task_id": task_id,
            "payload": payload,
        }])
        atomic_write(input_path, task_payload.encode())

        # Poll for result
        result = await _poll_task_response(host_dir, process, timeout_seconds)

        if result and result.get("status") == "completed":
            await db.execute(
                "UPDATE scheduled_tasks "
                "SET status = 'completed', completed_at = ?, result = ? "
                "WHERE id = ?",
                (
                    time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    json.dumps(result.get("result")),
                    task_id,
                ),
            )
            await db.commit()
            logger.info("Scheduled task %s completed successfully", task_id[:8])
        else:
            error_msg = "No task_result event received"
            if result:
                error_msg = result.get("error", str(result))
            await _apply_retry_or_fail(task_id, error_msg)

    except asyncio.CancelledError:
        # Timeout enforcement or scheduler shutdown
        await _apply_retry_or_fail(task_id, "Task cancelled (timeout or shutdown)")
        raise
    except Exception as e:
        logger.exception("Scheduled task %s failed", task_id[:8])
        await _apply_retry_or_fail(task_id, str(e))
    finally:
        _running_tasks.pop(task_id, None)
        # Clean up container
        if process and process.returncode is None:
            await kill_container(container_name)
        if record_id:
            now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            await db.execute(
                "UPDATE agent_containers SET status = 'stopped', stopped_at = ? "
                "WHERE id = ?",
                (now, record_id),
            )
            await db.commit()


async def _poll_task_response(
    host_dir: Path,
    process: asyncio.subprocess.Process,
    timeout_seconds: int,
) -> dict | None:
    """Poll response.json for a task_result event until process exits or timeout."""
    response_path = host_dir / "response.json"
    deadline = time.monotonic() + timeout_seconds

    while time.monotonic() < deadline:
        await asyncio.sleep(TASK_POLL_RESPONSE_INTERVAL)

        if response_path.exists():
            try:
                with open(response_path) as f:
                    events = json.load(f)
                os.remove(response_path)
            except (json.JSONDecodeError, OSError):
                try:
                    os.remove(response_path)
                except OSError:
                    pass
                continue

            for event in events:
                if event.get("type") == "task_result":
                    return event
                if event.get("type") == "system_error":
                    return {"status": "error", "error": event.get("error", "unknown")}

        # Process exited without producing a result
        if process.returncode is not None:
            return None

    return None  # Timeout


# ---------------------------------------------------------------------------
# Retry logic
# ---------------------------------------------------------------------------


async def _apply_retry_or_fail(task_id: str, error_message: str) -> None:
    """Re-queue a failed task with backoff, or mark as permanently failed."""
    db = await get_db()
    async with db.execute(
        "SELECT retry_count, max_retries FROM scheduled_tasks WHERE id = ?",
        (task_id,),
    ) as cur:
        row = await cur.fetchone()

    if not row:
        return

    retry_count, max_retries = row
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    if retry_count < max_retries:
        backoff_seconds = (retry_count + 1) * 30
        scheduled_at = time.strftime(
            "%Y-%m-%dT%H:%M:%SZ",
            time.gmtime(time.time() + backoff_seconds),
        )
        await db.execute(
            "UPDATE scheduled_tasks "
            "SET status = 'pending', retry_count = ?, "
            "error_message = ?, scheduled_at = ? "
            "WHERE id = ?",
            (retry_count + 1, error_message, scheduled_at, task_id),
        )
        logger.info(
            "Scheduled task %s retry %d/%d in %ds",
            task_id[:8], retry_count + 1, max_retries, backoff_seconds,
        )
    else:
        await db.execute(
            "UPDATE scheduled_tasks "
            "SET status = 'failed', completed_at = ?, error_message = ? "
            "WHERE id = ?",
            (now, error_message, task_id),
        )
        logger.warning("Scheduled task %s failed permanently: %s", task_id[:8], error_message)

    await db.commit()


# ---------------------------------------------------------------------------
# Timeout enforcement
# ---------------------------------------------------------------------------


async def _check_task_timeouts() -> None:
    """Kill scheduled task containers that have exceeded their timeout."""
    now = time.monotonic()
    timed_out = [
        info for info in _running_tasks.values()
        if now - info.started_at > info.timeout_seconds
    ]

    for info in timed_out:
        container_name = f"rhclaw-task-{info.agent_id[:8]}"
        logger.warning(
            "Scheduled task %s timed out after %ds, killing container %s",
            info.task_id[:8], info.timeout_seconds, container_name,
        )
        info.asyncio_task.cancel()


# ---------------------------------------------------------------------------
# Idle worker reaper (extracted from routes.py)
# ---------------------------------------------------------------------------


async def _reap_idle_workers() -> None:
    """Shut down worker containers idle longer than IDLE_TIMEOUT_SECONDS.

    Flow per container: send shutdown command via input.json -> wait up to 60s
    for clean exit -> force-kill on timeout.
    """
    # Import here to avoid circular dependency
    from orchestrator.routes import get_active_workers

    active_workers = get_active_workers()
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
        worker = active_workers.get(agent_id)
        reason = "Session ended due to inactivity"

        if worker:
            worker.shutting_down = True

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

                try:
                    await asyncio.wait_for(worker.process.wait(), timeout=60)
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
        w = active_workers.pop(agent_id, None)
        if w:
            if w.polling_task:
                w.polling_task.cancel()
            if w.monitor_task:
                w.monitor_task.cancel()
