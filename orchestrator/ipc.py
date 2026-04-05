from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import typing
import uuid
from datetime import datetime, timezone
from pathlib import Path

from orchestrator.db import get_db
from orchestrator.models import QueueStatusFrame

if typing.TYPE_CHECKING:
    from orchestrator.ws_manager import WebSocketManager

logger = logging.getLogger(__name__)

# Tracks source metadata for in-flight scheduled task messages per message_id.
# Set when flushing a scheduled task message, cleared on complete event.
_inflight_source: dict[str, dict] = {}


async def queue_message(
    session_id: str,
    message_id: str,
    content: str,
    *,
    source: str = "user",
    agentic_task_id: str | None = None,
    allowed_tools: list[str] | None = None,
) -> None:
    db = await get_db()
    payload_dict: dict = {
        "message_id": message_id,
        "type": "user_message",
        "content": content,
        "session_id": session_id,
        "source": source,
    }
    if agentic_task_id:
        payload_dict["agentic_task_id"] = agentic_task_id
    if allowed_tools:
        payload_dict["allowed_tools"] = allowed_tools
    payload = json.dumps(payload_dict)
    await db.execute(
        "INSERT INTO message_queue (id, session_id, payload, agentic_task_id) "
        "VALUES (?, ?, ?, ?)",
        (message_id, session_id, payload, agentic_task_id),
    )
    await db.commit()


async def store_scheduled_message(
    session_id: str,
    message_id: str,
    content: str,
    agentic_task_id: str,
    allowed_tools: list[str] | None = None,
) -> None:
    """Store a user message from a scheduled task and queue it for processing."""
    db = await get_db()
    metadata = json.dumps({
        "source": "scheduled_task",
        "agentic_task_id": agentic_task_id,
    })
    await db.execute(
        "INSERT INTO messages (id, session_id, role, content, metadata) "
        "VALUES (?, ?, 'user', ?, ?)",
        (message_id, session_id, content, metadata),
    )
    await db.commit()
    await queue_message(
        session_id, message_id, content,
        source="scheduled_task",
        agentic_task_id=agentic_task_id,
        allowed_tools=allowed_tools,
    )


async def queue_system_command(session_id: str, command: str) -> None:
    db = await get_db()
    cmd_id = str(uuid.uuid4())
    payload = json.dumps({
        "type": "system_command",
        "command": command,
    })
    await db.execute(
        "INSERT INTO message_queue (id, session_id, payload) VALUES (?, ?, ?)",
        (cmd_id, session_id, payload),
    )
    await db.commit()


async def get_queue_counts(session_id: str) -> dict[str, int]:
    db = await get_db()
    counts = {"queued": 0, "in_flight": 0, "processed": 0}
    async with db.execute(
        "SELECT status, COUNT(*) FROM message_queue WHERE session_id = ? GROUP BY status",
        (session_id,),
    ) as cur:
        async for row in cur:
            key = row[0].lower().replace("-", "_")
            counts[key] = row[1]
    return counts


def atomic_write(path: Path, data: bytes) -> None:
    temp_path = path.parent / f"{path.name}.tmp.{os.getpid()}"
    try:
        fd = os.open(str(temp_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
        try:
            os.write(fd, data)
            os.fsync(fd)
        finally:
            os.close(fd)
        os.rename(str(temp_path), str(path))
    except BaseException:
        try:
            os.unlink(str(temp_path))
        except FileNotFoundError:
            pass
        raise


# --- DB persistence (moved from stream_reader.py) ---


async def _db_get_metadata(db, row_id: str) -> tuple[str, dict] | None:
    async with db.execute(
        "SELECT content, metadata FROM messages WHERE id = ?", (row_id,),
    ) as cur:
        row = await cur.fetchone()
    if row is None:
        logger.warning("Message %s not found for update", row_id)
        return None
    content = row[0] or ""
    try:
        meta = json.loads(row[1]) if row[1] else {}
    except json.JSONDecodeError:
        meta = {}
    return content, meta


async def _db_ensure_row(
    row_id: str, session_id: str, extra_metadata: dict | None = None,
) -> None:
    meta: dict = {"blocks": []}
    if extra_metadata:
        meta.update(extra_metadata)
    metadata = json.dumps(meta)
    try:
        db = await get_db()
        await db.execute(
            "INSERT OR IGNORE INTO messages "
            "(id, session_id, role, content, status, metadata) "
            "VALUES (?, ?, 'assistant', '', 'streaming', ?)",
            (row_id, session_id, metadata),
        )
        await db.commit()
    except Exception:
        logger.exception("Failed to insert message %s", row_id)


async def _db_append_token(row_id: str, content: str) -> None:
    try:
        db = await get_db()
        row = await _db_get_metadata(db, row_id)
        if row is None:
            return
        current_content, meta = row

        blocks = meta.get("blocks", [])
        if blocks and blocks[-1]["type"] == "text":
            blocks[-1]["text"] += content
        else:
            blocks.append({"type": "text", "text": content})
        meta["blocks"] = blocks

        await db.execute(
            "UPDATE messages SET content = ?, metadata = ? WHERE id = ?",
            (current_content + content, json.dumps(meta), row_id),
        )
        await db.commit()
    except Exception:
        logger.exception("Failed to append token to %s", row_id)


async def _db_append_block(row_id: str, block: dict) -> None:
    try:
        db = await get_db()
        row = await _db_get_metadata(db, row_id)
        if row is None:
            return
        _, meta = row

        meta.setdefault("blocks", []).append(block)

        await db.execute(
            "UPDATE messages SET metadata = ? WHERE id = ?",
            (json.dumps(meta), row_id),
        )
        await db.commit()
    except Exception:
        logger.exception("Failed to append block to %s", row_id)


async def _db_update_tool_result(
    row_id: str, tool_call_id: str, output: str,
) -> None:
    try:
        db = await get_db()
        row = await _db_get_metadata(db, row_id)
        if row is None:
            return
        _, meta = row

        for block in meta.get("blocks", []):
            if (
                block["type"] == "tool_call"
                and block["tool"].get("tool_call_id") == tool_call_id
            ):
                block["tool"]["output"] = output
                break

        await db.execute(
            "UPDATE messages SET metadata = ? WHERE id = ?",
            (json.dumps(meta), row_id),
        )
        await db.commit()
    except Exception:
        logger.exception("Failed to update tool result in %s", row_id)


async def _db_complete(
    row_id: str, content: str, usage: dict | None,
) -> None:
    try:
        db = await get_db()
        row = await _db_get_metadata(db, row_id)
        if row is None:
            return
        _, meta = row

        if usage:
            meta["usage"] = usage

        await db.execute(
            "UPDATE messages SET content = ?, status = 'complete', metadata = ? "
            "WHERE id = ?",
            (content, json.dumps(meta), row_id),
        )
        await db.commit()
    except Exception:
        logger.exception("Failed to complete message %s", row_id)


# --- Event processing ---


async def _process_event(
    event: dict, session_id: str, ws_mgr: WebSocketManager,
    source_metadata: dict | None = None,
) -> str | None:
    """Process a single worker event. Returns the message_id if DB was touched."""
    event_type = event.get("type")

    # Forward context_cleared directly — it has no message_id
    if event_type == "status" and event.get("status") == "context_cleared":
        await ws_mgr.send(json.dumps(event))
        return None

    if event_type == "schedule_compaction":
        date = event.get("date")
        if date:
            await _schedule_compaction_task(session_id, date)
        return None

    message_id = event.get("message_id", "")
    if not message_id:
        return None

    row_id = f"assistant-{message_id}"

    if event_type == "status" and event.get("status") == "thinking":
        await _db_ensure_row(row_id, session_id, source_metadata)

    elif event_type == "token":
        await _db_ensure_row(row_id, session_id, source_metadata)
        await _db_append_token(row_id, event.get("content", ""))

    elif event_type == "tool_call":
        await _db_ensure_row(row_id, session_id, source_metadata)
        block = {
            "type": "tool_call",
            "tool": {
                "tool_name": event.get("tool_name", "unknown"),
                "tool_input": event.get("tool_input", {}),
                "tool_call_id": event.get("tool_call_id", ""),
            },
        }
        await _db_append_block(row_id, block)

    elif event_type == "tool_result":
        await _db_update_tool_result(
            row_id, event.get("tool_call_id", ""), event.get("output", ""),
        )

    elif event_type == "complete":
        await _db_complete(
            row_id, event.get("content", ""), event.get("usage"),
        )
        # Eagerly update agentic_tasks.last_result for the schedules view
        if source_metadata and source_metadata.get("agentic_task_id"):
            task_id = source_metadata["agentic_task_id"]
            now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            try:
                db = await get_db()
                await db.execute(
                    "UPDATE agentic_tasks SET last_executed_at = ?, last_result = ? "
                    "WHERE id = ?",
                    (now, event.get("content", ""), task_id),
                )
                await db.commit()
            except Exception:
                logger.exception("Failed to update agentic task %s last_result", task_id)

    elif event_type == "status" and event.get("status") == "done":
        # Worker finished processing — no DB action needed
        pass

    elif event_type == "system_error":
        logger.warning(
            "Worker error for session %s: %s", session_id, event.get("error"),
        )

    else:
        # Ignore unknown events (e.g. "generating" status)
        return None

    return row_id


# --- Scheduled task helpers ---


async def _handle_tool_request(session_id: str, request: dict) -> dict:
    """Dispatch a tool execution request from the worker and return the result."""
    request_id = request.get("request_id", "")
    action = request.get("action", "")
    params = request.get("parameters", {})

    try:
        db = await get_db()

        # Look up agent_id from session
        async with db.execute(
            "SELECT agent_id FROM sessions WHERE id = ?", (session_id,),
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return {"request_id": request_id, "status": "error", "error": "Session not found"}
        agent_id = row[0]

        if action == "create_schedule":
            task_id = str(uuid.uuid4())
            prompt = params.get("prompt", "")
            allowed_tools = json.dumps(params.get("allowed_tools", []))
            interval_minutes = max(int(params.get("interval_minutes", 60)), 5)
            interval_seconds = interval_minutes * 60

            await db.execute(
                "INSERT INTO agentic_tasks (id, agent_id, prompt, allowed_tools, interval_seconds) "
                "VALUES (?, ?, ?, ?, ?)",
                (task_id, agent_id, prompt, allowed_tools, interval_seconds),
            )
            await db.commit()
            logger.info("Created agentic task %s for agent %s", task_id[:8], agent_id[:8])
            return {
                "request_id": request_id,
                "status": "ok",
                "data": {
                    "task_id": task_id,
                    "prompt": prompt,
                    "interval_minutes": interval_minutes,
                    "status": "active",
                },
            }

        elif action == "list_schedules":
            status_filter = params.get("status")
            sql = (
                "SELECT t.id, t.prompt, t.interval_seconds, t.status, "
                "t.last_executed_at, t.allowed_tools "
                "FROM agentic_tasks t "
                "JOIN sessions s ON s.agent_id = t.agent_id "
                "WHERE s.id = ?"
            )
            sql_params: list = [session_id]
            if status_filter:
                sql += " AND t.status = ?"
                sql_params.append(status_filter)
            async with db.execute(sql, sql_params) as cur:
                rows = await cur.fetchall()
            schedules = []
            for r in rows:
                schedules.append({
                    "task_id": r[0],
                    "prompt": r[1],
                    "interval_minutes": r[2] // 60,
                    "status": r[3],
                    "last_executed_at": r[4],
                    "allowed_tools": json.loads(r[5]) if r[5] else [],
                })
            return {"request_id": request_id, "status": "ok", "data": {"schedules": schedules}}

        elif action == "get_schedule":
            task_id = params.get("task_id", "")
            async with db.execute(
                "SELECT id, prompt, interval_seconds, status, last_executed_at, "
                "allowed_tools, last_result, created_at "
                "FROM agentic_tasks WHERE id = ?",
                (task_id,),
            ) as cur:
                r = await cur.fetchone()
            if not r:
                return {"request_id": request_id, "status": "error", "error": "Schedule not found"}
            return {
                "request_id": request_id,
                "status": "ok",
                "data": {
                    "task_id": r[0], "prompt": r[1],
                    "interval_minutes": r[2] // 60, "status": r[3],
                    "last_executed_at": r[4],
                    "allowed_tools": json.loads(r[5]) if r[5] else [],
                    "last_result": r[6], "created_at": r[7],
                },
            }

        elif action == "update_schedule":
            task_id = params.get("task_id", "")
            updates: list[str] = []
            values: list = []
            if "prompt" in params:
                updates.append("prompt = ?")
                values.append(params["prompt"])
            if "interval_minutes" in params:
                interval = max(int(params["interval_minutes"]), 5)
                updates.append("interval_seconds = ?")
                values.append(interval * 60)
            if "allowed_tools" in params:
                updates.append("allowed_tools = ?")
                values.append(json.dumps(params["allowed_tools"]))
            if not updates:
                return {"request_id": request_id, "status": "error", "error": "No fields to update"}
            values.append(task_id)
            await db.execute(
                f"UPDATE agentic_tasks SET {', '.join(updates)} WHERE id = ?",
                values,
            )
            await db.commit()
            return {"request_id": request_id, "status": "ok", "data": {"task_id": task_id, "updated": True}}

        elif action == "delete_schedule":
            task_id = params.get("task_id", "")
            cursor = await db.execute("DELETE FROM agentic_tasks WHERE id = ?", (task_id,))
            await db.commit()
            if cursor.rowcount == 0:
                return {"request_id": request_id, "status": "error", "error": "Schedule not found"}
            return {"request_id": request_id, "status": "ok", "data": {"task_id": task_id, "deleted": True}}

        elif action == "pause_schedule":
            task_id = params.get("task_id", "")
            cursor = await db.execute(
                "UPDATE agentic_tasks SET status = 'paused' WHERE id = ? AND status = 'active'",
                (task_id,),
            )
            await db.commit()
            if cursor.rowcount == 0:
                return {"request_id": request_id, "status": "error", "error": "Schedule not found or not active"}
            return {"request_id": request_id, "status": "ok", "data": {"task_id": task_id, "status": "paused"}}

        elif action == "resume_schedule":
            task_id = params.get("task_id", "")
            cursor = await db.execute(
                "UPDATE agentic_tasks SET status = 'active' WHERE id = ? AND status = 'paused'",
                (task_id,),
            )
            await db.commit()
            if cursor.rowcount == 0:
                return {"request_id": request_id, "status": "error", "error": "Schedule not found or not paused"}
            return {"request_id": request_id, "status": "ok", "data": {"task_id": task_id, "status": "active"}}

        else:
            return {"request_id": request_id, "status": "error", "error": f"Unknown action: {action}"}

    except Exception as e:
        logger.exception("Error handling tool request %s", action)
        return {"request_id": request_id, "status": "error", "error": str(e)}


async def _schedule_compaction_task(session_id: str, date: str) -> None:
    """Insert a memory_compaction scheduled task for the agent owning this session."""
    db = await get_db()
    async with db.execute(
        "SELECT agent_id FROM sessions WHERE id = ?", (session_id,),
    ) as cur:
        row = await cur.fetchone()
    if not row:
        logger.warning("Cannot schedule compaction: session %s not found", session_id)
        return

    agent_id = row[0]
    task_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO scheduled_tasks (id, agent_id, task_type, payload, timeout_seconds) "
        "VALUES (?, ?, 'memory_compaction', ?, 120)",
        (task_id, agent_id, json.dumps({"date": date})),
    )
    await db.commit()
    logger.info(
        "Scheduled memory compaction for agent %s date %s (task %s)",
        agent_id[:8], date, task_id[:8],
    )


# --- Queue status ---


async def _send_queue_status(ws_mgr: WebSocketManager, session_id: str) -> None:
    counts = await get_queue_counts(session_id)
    frame = QueueStatusFrame(**counts)
    await ws_mgr.send(frame.model_dump_json())


# --- Polling loop ---


async def _polling_loop(
    session_id: str, host_dir: Path, ws_mgr: WebSocketManager
) -> None:
    input_path = host_dir / "input.json"
    output_path = host_dir / "output.json"
    request_path = host_dir / "request.json"
    response_path = host_dir / "response.json"
    db = await get_db()

    while True:
        await asyncio.sleep(0.5)
        try:
            # --- Input ACK: IN-FLIGHT messages + input.json gone = PROCESSED ---
            async with db.execute(
                "SELECT COUNT(*) FROM message_queue "
                "WHERE session_id = ? AND status = 'IN-FLIGHT'",
                (session_id,),
            ) as cur:
                row = await cur.fetchone()
                in_flight_count = row[0]

            if in_flight_count > 0 and not input_path.exists():
                now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                await db.execute(
                    "UPDATE message_queue SET status = 'PROCESSED', processed_at = ? "
                    "WHERE session_id = ? AND status = 'IN-FLIGHT'",
                    (now, session_id),
                )
                await db.commit()
                await _send_queue_status(ws_mgr, session_id)

            # --- Input flush: QUEUED messages + no input.json = write input.json ---
            async with db.execute(
                "SELECT id, payload FROM message_queue "
                "WHERE session_id = ? AND status = 'QUEUED' "
                "ORDER BY created_at",
                (session_id,),
            ) as cur:
                queued = await cur.fetchall()

            if queued and not input_path.exists():
                messages = [json.loads(row[1]) for row in queued]
                now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                for msg in messages:
                    msg["timestamp"] = now

                # Track source metadata per message for scheduled tasks
                for msg in messages:
                    if msg.get("agentic_task_id") and msg.get("message_id"):
                        _inflight_source[msg["message_id"]] = {
                            "source": "scheduled_task",
                            "agentic_task_id": msg["agentic_task_id"],
                        }

                atomic_write(input_path, json.dumps(messages).encode())

                ids = [row[0] for row in queued]
                placeholders = ",".join("?" * len(ids))
                await db.execute(
                    f"UPDATE message_queue SET status = 'IN-FLIGHT', flushed_at = ? "
                    f"WHERE id IN ({placeholders})",
                    (now, *ids),
                )
                # Update last_activity on the container (drives idle reaper)
                await db.execute(
                    "UPDATE agent_containers SET last_activity = ? "
                    "WHERE session_id = ? AND status IN ('running', 'idle')",
                    (now, session_id),
                )
                await db.commit()
                await _send_queue_status(ws_mgr, session_id)

            # --- Request polling: handle tool execution requests from worker ---
            if request_path.exists():
                try:
                    with open(request_path) as f:
                        request = json.load(f)
                    os.remove(request_path)
                except (json.JSONDecodeError, OSError) as e:
                    logger.warning("Error reading request.json: %s", e)
                    try:
                        os.remove(request_path)
                    except OSError:
                        pass
                    request = None

                if request:
                    result = await _handle_tool_request(session_id, request)
                    atomic_write(
                        response_path,
                        json.dumps(result).encode(),
                    )

            # --- Output polling: read output.json from worker ---
            if output_path.exists():
                try:
                    with open(output_path) as f:
                        events = json.load(f)
                    os.remove(output_path)
                except (json.JSONDecodeError, OSError) as e:
                    logger.warning("Error reading output.json: %s", e)
                    try:
                        os.remove(output_path)
                    except OSError:
                        pass
                    events = []

                # Process events and collect unique message_ids for notification
                notified: set[str] = set()
                for event in events:
                    try:
                        msg_id = event.get("message_id", "")
                        source_meta = _inflight_source.get(msg_id)
                        row_id = await _process_event(
                            event, session_id, ws_mgr, source_meta,
                        )
                        if row_id:
                            notified.add(row_id)
                        # Clear source metadata when this message completes
                        if event.get("type") == "complete" and msg_id:
                            _inflight_source.pop(msg_id, None)
                    except Exception:
                        logger.exception(
                            "Error processing output event for session %s",
                            session_id,
                        )

                # Send one message_updated notification per unique message
                for row_id in notified:
                    frame = json.dumps({
                        "type": "message_updated",
                        "message_id": row_id,
                    })
                    await ws_mgr.send(frame)

        except (ConnectionError, RuntimeError):
            # WebSocket disconnected
            break
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Polling loop error for session %s", session_id)


def start_polling_loop(
    session_id: str, host_dir: Path, ws_mgr: WebSocketManager
) -> asyncio.Task:
    return asyncio.create_task(
        _polling_loop(session_id, host_dir, ws_mgr),
        name=f"poll-{session_id[:8]}",
    )
