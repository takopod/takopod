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
from datetime import datetime, timezone
from pathlib import Path

from orchestrator.container_manager import kill_container, spawn_scheduled_container
from orchestrator.db import get_db
from orchestrator.ipc import atomic_write
from orchestrator.models import SystemErrorFrame
from orchestrator.ws_manager import WS_CLOSE_IDLE_TIMEOUT

logger = logging.getLogger(__name__)

IDLE_TIMEOUT_SECONDS = int(os.environ.get("IDLE_TIMEOUT_SECONDS", "300"))
INFLIGHT_HARD_TIMEOUT = int(os.environ.get("INFLIGHT_HARD_TIMEOUT", "600"))
SCHEDULER_TICK = 10  # seconds between scheduler iterations
IDLE_REAPER_TICKS = 3  # run idle reaper every N ticks (30s at TICK=10)
AGENTIC_TASK_TICKS = 3  # poll agentic tasks every N ticks (30s at TICK=10)

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

# Track running agentic tasks by agentic_task_id -> asyncio.Task
_running_agentic: dict[str, asyncio.Task] = {}


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

        if tick % AGENTIC_TASK_TICKS == 0:
            try:
                await _poll_agentic_tasks()
            except Exception:
                logger.exception("Scheduler: error polling agentic tasks")

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
    container_name = f"takopod-task-{agent_id[:8]}"

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
    """Poll output.json for a task_result event until process exits or timeout."""
    response_path = host_dir / "output.json"
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
# Agentic (recurring) task runner
# ---------------------------------------------------------------------------


async def _poll_agentic_tasks() -> None:
    """Find active agentic tasks that are due for execution."""
    # Clean up completed asyncio tasks
    done = [tid for tid, t in _running_agentic.items() if t.done()]
    for tid in done:
        _running_agentic.pop(tid, None)

    db = await get_db()

    # --- Interval tasks (existing logic) ---
    async with db.execute(
        "SELECT id, agent_id, prompt, allowed_tools, interval_seconds, model "
        "FROM agentic_tasks "
        "WHERE status = 'active' AND trigger_type = 'interval' "
        "  AND (last_executed_at IS NULL "
        "       OR last_executed_at <= strftime('%Y-%m-%dT%H:%M:%SZ', 'now', "
        "          '-' || interval_seconds || ' seconds'))",
    ) as cur:
        interval_rows = await cur.fetchall()

    for task_id, agent_id, prompt, allowed_tools_json, interval_seconds, model in interval_rows:
        if task_id in _running_agentic:
            continue
        allowed_tools = json.loads(allowed_tools_json) if allowed_tools_json else []
        task = asyncio.create_task(
            execute_agentic_task(task_id, agent_id, prompt, allowed_tools, model=model),
            name=f"agentic-{task_id[:8]}",
        )
        _running_agentic[task_id] = task

    # --- Checker-based tasks (file_watch, github_pr, github_issues, slack_channel) ---
    from orchestrator.checkers import CHECKERS

    checker_types = list(CHECKERS.keys())
    if checker_types:
        placeholders = ",".join("?" for _ in checker_types)
        async with db.execute(
            "SELECT id, agent_id, prompt, allowed_tools, trigger_type, "
            "trigger_config, cursor, model "
            "FROM agentic_tasks "
            "WHERE status = 'active' "
            f"  AND trigger_type IN ({placeholders}) "
            "  AND (last_checked_at IS NULL "
            "       OR last_checked_at <= strftime('%Y-%m-%dT%H:%M:%SZ', 'now', "
            "          '-' || interval_seconds || ' seconds')) "
            "ORDER BY last_checked_at ASC NULLS FIRST "
            "LIMIT 1",
            checker_types,
        ) as cur:
            row = await cur.fetchone()

        if row:
            (task_id, agent_id, prompt, allowed_tools_json,
             trigger_type, trigger_config_json, cursor_json, model) = row
            if task_id not in _running_agentic:
                trigger_config = json.loads(trigger_config_json) if trigger_config_json else {}
                cursor = json.loads(cursor_json) if cursor_json else {}
                allowed_tools = json.loads(allowed_tools_json) if allowed_tools_json else []
                # file_watch needs agent_id in config for directory resolution
                if trigger_type == "file_watch":
                    trigger_config["agent_id"] = agent_id
                logger.info(
                    "Polling checker %s for task %s (agent %s)",
                    trigger_type, task_id[:8], agent_id[:8],
                )
                task = asyncio.create_task(
                    _run_checker_task(
                        task_id, agent_id, prompt, allowed_tools,
                        trigger_type, trigger_config, cursor, model,
                    ),
                    name=f"agentic-check-{task_id[:8]}",
                )
                _running_agentic[task_id] = task


async def _run_checker_task(
    task_id: str,
    agent_id: str,
    prompt: str,
    allowed_tools: list[str],
    trigger_type: str,
    trigger_config: dict,
    cursor: dict,
    model: str | None,
) -> None:
    """Run checker, invoke agent only if changes detected, update cursor."""
    from orchestrator.checkers import run_checker

    db = await get_db()
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    try:
        result = await run_checker(trigger_type, trigger_config, cursor)

        # Always update last_checked_at
        await db.execute(
            "UPDATE agentic_tasks SET last_checked_at = ? WHERE id = ?",
            (now, task_id),
        )
        await db.commit()

        if result.changed:
            logger.info(
                "Checker %s detected changes for task %s, invoking agent",
                trigger_type, task_id[:8],
            )
            enriched_prompt = f"{prompt}\n\n{result.summary}"
            success = await execute_agentic_task(
                task_id, agent_id, enriched_prompt, allowed_tools,
                model=model, _caller_managed=True,
            )
            # Cursor advances only after successful agent completion
            if success:
                await db.execute(
                    "UPDATE agentic_tasks SET cursor = ? WHERE id = ?",
                    (json.dumps(result.new_cursor), task_id),
                )
                await db.commit()
        else:
            logger.info(
                "Checker %s found no changes for task %s",
                trigger_type, task_id[:8],
            )
            # Update cursor even on no-change (e.g. new ETag)
            if result.new_cursor != cursor:
                await db.execute(
                    "UPDATE agentic_tasks SET cursor = ? WHERE id = ?",
                    (json.dumps(result.new_cursor), task_id),
                )
                await db.commit()
    except Exception:
        logger.exception("Checker task %s (%s) failed", task_id[:8], trigger_type)
    finally:
        _running_agentic.pop(task_id, None)


async def execute_agentic_task(
    task_id: str,
    agent_id: str,
    prompt: str,
    allowed_tools: list[str],
    *,
    model: str | None = None,
    _caller_managed: bool = False,
) -> bool:
    """Queue a scheduled task prompt through the normal message path.

    Returns True on success, False on failure.  When *_caller_managed* is
    True the caller owns the ``_running_agentic`` entry and backoff — this
    function will not pop or apply backoff itself.
    """
    from orchestrator.ipc import _activity_signaled, store_scheduled_message
    from orchestrator.routes import ensure_worker_headless

    db = await get_db()
    message_id = str(uuid.uuid4())
    success = False

    try:
        await ensure_worker_headless(agent_id)
        await store_scheduled_message(
            agent_id, message_id, prompt, task_id, allowed_tools,
            model=model,
        )

        last_result = await _wait_for_completion(message_id, timeout_seconds=300)

        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        await db.execute(
            "UPDATE agentic_tasks SET last_executed_at = ?, last_result = ? "
            "WHERE id = ?",
            (now, last_result, task_id),
        )
        await db.commit()
        logger.info("Agentic task %s executed successfully", task_id[:8])
        success = not (last_result or "").startswith("Error:")

    except Exception:
        logger.exception("Agentic task %s failed", task_id[:8])
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        try:
            await db.execute(
                "UPDATE agentic_tasks SET last_executed_at = ?, last_result = ? "
                "WHERE id = ?",
                (now, "Error: execution failed", task_id),
            )
            await db.commit()
        except Exception:
            pass
    finally:
        if not _caller_managed:
            _running_agentic.pop(task_id, None)
            await _apply_backoff(task_id, _activity_signaled)

    return success


async def _apply_backoff(task_id: str, activity_signaled: set[str]) -> None:
    """Double the task's interval if backoff is enabled and no activity was signaled."""
    if task_id in activity_signaled:
        activity_signaled.discard(task_id)
        return

    db = await get_db()
    async with db.execute(
        "SELECT interval_seconds, base_interval_seconds, max_interval_seconds "
        "FROM agentic_tasks WHERE id = ?",
        (task_id,),
    ) as cur:
        row = await cur.fetchone()

    if not row:
        return
    interval, base, max_interval = row
    if base is None or max_interval is None:
        return

    new_interval = min(interval * 2, max_interval)
    if new_interval != interval:
        await db.execute(
            "UPDATE agentic_tasks SET interval_seconds = ? WHERE id = ?",
            (new_interval, task_id),
        )
        await db.commit()
        logger.info(
            "Agentic task %s backoff: %ds -> %ds (max %ds)",
            task_id[:8], interval, new_interval, max_interval,
        )


async def _wait_for_completion(
    message_id: str,
    timeout_seconds: int = 300,
) -> str:
    """Poll the messages table until the assistant response is complete."""
    db = await get_db()
    row_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, message_id))
    deadline = time.monotonic() + timeout_seconds

    while time.monotonic() < deadline:
        await asyncio.sleep(2.0)

        async with db.execute(
            "SELECT content, status FROM messages WHERE id = ?",
            (row_id,),
        ) as cur:
            row = await cur.fetchone()

        if row and row[1] == "complete":
            return row[0] or ""

    return "Error: Timed out waiting for response"


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
        container_name = f"takopod-task-{info.agent_id[:8]}"
        logger.warning(
            "Scheduled task %s timed out after %ds, killing container %s",
            info.task_id[:8], info.timeout_seconds, container_name,
        )
        info.asyncio_task.cancel()



# ---------------------------------------------------------------------------
# Idle worker reaper (extracted from routes.py)
# ---------------------------------------------------------------------------


async def _cancel_task(task: asyncio.Task | None) -> None:
    """Cancel a task and wait for it to finish."""
    if task is None or task.done():
        return
    task.cancel()
    try:
        await task
    except (asyncio.CancelledError, Exception):
        pass


async def _reap_idle_workers() -> None:
    """Shut down worker containers idle longer than IDLE_TIMEOUT_SECONDS.

    Flow per container: send shutdown command via input.json -> wait up to 60s
    for clean exit -> force-kill on timeout.
    """
    # Import here to avoid circular dependency
    from orchestrator.routes import get_active_workers, get_workers_lock

    active_workers = get_active_workers()
    workers_lock = get_workers_lock()
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
        container_name = f"takopod-{agent_id[:8]}"

        # Skip containers that still have messages being processed,
        # unless they've been in-flight longer than the hard timeout.
        async with db.execute(
            "SELECT COUNT(*), MIN(flushed_at) FROM message_queue "
            "WHERE agent_id = ? AND status = 'IN-FLIGHT'",
            (agent_id,),
        ) as cur:
            row = await cur.fetchone()
        if row and row[0] > 0:
            oldest_flushed = row[1]
            if not oldest_flushed:
                logger.warning(
                    "In-flight message for %s has no flushed_at, "
                    "allowing reap",
                    container_name,
                )
            else:
                flushed_dt = datetime.fromisoformat(
                    oldest_flushed.replace("Z", "+00:00")
                )
                age = (datetime.now(timezone.utc) - flushed_dt).total_seconds()
                if age < INFLIGHT_HARD_TIMEOUT:
                    logger.debug(
                        "Skipping reap of %s: %d in-flight message(s), "
                        "oldest flushed %ds ago",
                        container_name, row[0], int(age),
                    )
                    continue
                logger.warning(
                    "In-flight message for %s exceeded hard timeout "
                    "(%ds > %ds), proceeding with reap",
                    container_name, int(age), INFLIGHT_HARD_TIMEOUT,
                )

        reason = "Session ended due to inactivity"
        old_polling = None
        old_monitor = None

        # Grab worker reference and mark as shutting down under lock
        async with workers_lock:
            worker = active_workers.get(agent_id)
            if worker:
                worker.shutting_down = True

        if worker:
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

        # Clean up in-memory state under lock
        async with workers_lock:
            w = active_workers.pop(agent_id, None)
            if w:
                old_polling = w.polling_task
                old_monitor = w.monitor_task
                w.polling_task = None
                w.monitor_task = None
        await _cancel_task(old_polling)
        await _cancel_task(old_monitor)
