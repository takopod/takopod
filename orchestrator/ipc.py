from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from sqlite3 import Error as SqliteError, IntegrityError
import typing
import uuid
from datetime import datetime, timezone
from pathlib import Path

from orchestrator.db import get_db
from orchestrator.models import QueueStatusFrame

if typing.TYPE_CHECKING:
    from orchestrator.gh_approval import GhApprovalManager
    from orchestrator.mcp_manager import McpServerManager
    from orchestrator.ws_manager import WebSocketManager

logger = logging.getLogger(__name__)

# Tracks source metadata for in-flight scheduled task messages per message_id.
# Set when flushing a scheduled task message, cleared on complete event.
_inflight_source: dict[str, dict] = {}


async def queue_message(
    agent_id: str,
    message_id: str,
    content: str,
    *,
    source: str = "user",
    agentic_task_id: str | None = None,
    allowed_tools: list[str] | None = None,
    attachments: list[str] | None = None,
) -> None:
    db = await get_db()
    payload_dict: dict = {
        "message_id": message_id,
        "type": "user_message",
        "content": content,
        "agent_id": agent_id,
        "source": source,
    }
    if agentic_task_id:
        payload_dict["agentic_task_id"] = agentic_task_id
    if allowed_tools:
        payload_dict["allowed_tools"] = allowed_tools
    if attachments:
        payload_dict["attachments"] = attachments
    payload = json.dumps(payload_dict)
    await db.execute(
        "INSERT INTO message_queue (id, agent_id, payload, agentic_task_id) "
        "VALUES (?, ?, ?, ?)",
        (message_id, agent_id, payload, agentic_task_id),
    )
    await db.commit()


async def store_scheduled_message(
    agent_id: str,
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
        "INSERT INTO messages (id, agent_id, role, content, metadata) "
        "VALUES (?, ?, 'user', ?, ?)",
        (message_id, agent_id, content, metadata),
    )
    await db.commit()
    await queue_message(
        agent_id, message_id, content,
        source="scheduled_task",
        agentic_task_id=agentic_task_id,
        allowed_tools=allowed_tools,
    )


async def store_bootstrap_message(
    agent_id: str,
    message_id: str,
    content: str,
) -> None:
    """Store a bootstrap prompt (hidden) and queue it for processing."""
    db = await get_db()
    metadata = json.dumps({"source": "bootstrap"})
    await db.execute(
        "INSERT INTO messages (id, agent_id, role, content, metadata, visibility) "
        "VALUES (?, ?, 'user', ?, ?, 'hidden')",
        (message_id, agent_id, content, metadata),
    )
    await db.commit()
    await queue_message(agent_id, message_id, content, source="bootstrap")


async def store_slack_message(
    agent_id: str,
    message_id: str,
    content: str,
    channel_id: str,
    thread_ts: str,
    *,
    attachments: list[str] | None = None,
) -> None:
    """Store a user message from Slack and queue it for processing."""
    db = await get_db()
    meta: dict = {
        "source": "slack",
        "channel_id": channel_id,
        "thread_ts": thread_ts,
    }
    if attachments:
        meta["attachments"] = attachments
    metadata = json.dumps(meta)
    await db.execute(
        "INSERT INTO messages (id, agent_id, role, content, metadata) "
        "VALUES (?, ?, 'user', ?, ?)",
        (message_id, agent_id, content, metadata),
    )
    await db.commit()
    await queue_message(
        agent_id, message_id, content, source="slack", attachments=attachments,
    )


async def queue_system_command(agent_id: str, command: str) -> None:
    db = await get_db()
    cmd_id = str(uuid.uuid4())
    payload = json.dumps({
        "type": "system_command",
        "command": command,
    })
    await db.execute(
        "INSERT INTO message_queue (id, agent_id, payload) VALUES (?, ?, ?)",
        (cmd_id, agent_id, payload),
    )
    await db.commit()


async def get_queue_counts(agent_id: str) -> dict[str, int]:
    db = await get_db()
    counts = {"queued": 0, "in_flight": 0}
    async with db.execute(
        "SELECT status, COUNT(*) FROM message_queue WHERE agent_id = ? GROUP BY status",
        (agent_id,),
    ) as cur:
        async for row in cur:
            key = row[0].lower().replace("-", "_")
            if key in counts:
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
    row_id: str, agent_id: str, extra_metadata: dict | None = None,
) -> None:
    meta: dict = {"blocks": []}
    if extra_metadata:
        meta.update(extra_metadata)
    metadata = json.dumps(meta)
    try:
        db = await get_db()
        await db.execute(
            "INSERT OR IGNORE INTO messages "
            "(id, agent_id, role, content, status, metadata) "
            "VALUES (?, ?, 'assistant', '', 'streaming', ?)",
            (row_id, agent_id, metadata),
        )
        await db.commit()
    except SqliteError:
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
    except (SqliteError, KeyError, TypeError):
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
    except (SqliteError, KeyError, TypeError):
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
    except (SqliteError, KeyError, TypeError):
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
    except (SqliteError, KeyError, TypeError):
        logger.exception("Failed to complete message %s", row_id)


# --- Event processing ---


async def _process_event(
    event: dict, agent_id: str, ws_mgr: WebSocketManager,
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
            await _schedule_compaction_task(agent_id, date)
        return None

    message_id = event.get("message_id", "")
    if not message_id:
        return None

    row_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, message_id))

    if event_type == "status" and event.get("status") == "thinking":
        await _db_ensure_row(row_id, agent_id, source_metadata)

    elif event_type == "token":
        await _db_ensure_row(row_id, agent_id, source_metadata)
        await _db_append_token(row_id, event.get("content", ""))

    elif event_type == "assistant_message":
        # Snapshot of the full assistant text so far.  Overwrites content
        # to keep the DB in sync even when individual token events were
        # batched together and the orchestrator only sees one output.json.
        await _db_ensure_row(row_id, agent_id, source_metadata)
        content = event.get("content", "")
        try:
            db = await get_db()
            await db.execute(
                "UPDATE messages SET content = ? WHERE id = ?",
                (content, row_id),
            )
            await db.commit()
        except SqliteError:
            logger.exception("Failed to update assistant_message %s", row_id)

    elif event_type == "tool_call":
        await _db_ensure_row(row_id, agent_id, source_metadata)
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
            except SqliteError:
                logger.exception("Failed to update agentic task %s last_result", task_id)

        # Post response back to Slack thread
        if source_metadata and source_metadata.get("source") == "slack":
            ch = source_metadata.get("channel_id", "")
            ts = source_metadata.get("thread_ts", "")
            if ch and ts:
                # Look up agent name for the [bot:name] prefix
                agent_name = ""
                try:
                    db = await get_db()
                    async with db.execute(
                        "SELECT name FROM agents WHERE id = ?", (agent_id,),
                    ) as cur:
                        name_row = await cur.fetchone()
                    if name_row:
                        agent_name = name_row[0].lower()
                except SqliteError:
                    logger.exception("Failed to look up agent name for Slack reply")

                reply_ts: str | None = None
                try:
                    from orchestrator.slack_poller import post_slack_reply
                    reply_ts = await post_slack_reply(
                        ch, ts, event.get("content", ""),
                        agent_name=agent_name,
                    )
                except Exception:
                    logger.exception("Failed to post Slack reply")
                # Auto-register thread so follow-up replies are polled.
                # Use the reply's ts as last_ts so the next poll cycle
                # doesn't re-fetch the entire thread history.
                try:
                    thread_id = str(uuid.uuid4())
                    await db.execute(
                        "INSERT OR IGNORE INTO slack_active_threads "
                        "(id, channel_id, thread_ts, agent_id, last_ts) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (thread_id, ch, ts, agent_id, reply_ts or ts),
                    )
                    await db.commit()
                except SqliteError:
                    logger.exception("Failed to auto-register slack thread")

    elif event_type == "status" and event.get("status") == "done":
        # Worker finished processing — no DB action needed
        pass

    elif event_type == "system_error":
        logger.warning(
            "Worker error for agent %s: %s", agent_id, event.get("error"),
        )

    else:
        # Ignore unknown events (e.g. "generating" status)
        return None

    return row_id


# --- Scheduled task helpers ---


async def _handle_tool_request(
    agent_id: str,
    request: dict,
    mcp_manager: McpServerManager | None = None,
    ws_manager: WebSocketManager | None = None,
    approval_manager: GhApprovalManager | None = None,
) -> dict:
    """Dispatch a tool execution request from the worker and return the result."""
    request_id = request.get("request_id", "")
    action = request.get("action", "")
    params = request.get("parameters", {})

    try:
        db = await get_db()

        if action == "create_schedule":
            task_id = str(uuid.uuid4())
            prompt = params.get("prompt", "")
            allowed_tools = json.dumps(params.get("allowed_tools", []))
            trigger_type = params.get("trigger_type", "interval")
            trigger_config: dict = {}
            trigger_secret = None

            if trigger_type == "file_watch":
                watch_dir = params.get("watch_dir", "")
                if not watch_dir:
                    return {"request_id": request_id, "status": "error", "error": "watch_dir required for file_watch trigger"}
                if ".." in watch_dir or watch_dir.startswith("/"):
                    return {"request_id": request_id, "status": "error", "error": "watch_dir must be a relative path within workspace"}
                initial_snapshot = await _get_initial_snapshot(agent_id, watch_dir)
                trigger_config = {"watch_dir": watch_dir, "last_snapshot": initial_snapshot}
                interval_minutes = 0
                interval_seconds = 0
            elif trigger_type == "webhook":
                interval_minutes = 0
                interval_seconds = 0
                import secrets
                trigger_secret = secrets.token_urlsafe(24)
            else:
                interval_minutes = max(int(params.get("interval_minutes", 60)), 5)
                interval_seconds = interval_minutes * 60

            await db.execute(
                "INSERT INTO agentic_tasks "
                "(id, agent_id, prompt, allowed_tools, interval_seconds, "
                "trigger_type, trigger_config, trigger_secret) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (task_id, agent_id, prompt, allowed_tools, interval_seconds,
                 trigger_type, json.dumps(trigger_config), trigger_secret),
            )
            await db.commit()
            logger.info("Created agentic task %s (%s) for agent %s", task_id[:8], trigger_type, agent_id[:8])

            data: dict[str, Any] = {
                "task_id": task_id,
                "prompt": prompt,
                "trigger_type": trigger_type,
                "status": "active",
            }
            if trigger_type == "interval":
                data["interval_minutes"] = interval_minutes
            if trigger_type == "webhook":
                data["webhook_url"] = f"/api/agents/{agent_id}/trigger/{task_id}"
                data["webhook_secret"] = trigger_secret
            return {"request_id": request_id, "status": "ok", "data": data}

        elif action == "list_schedules":
            status_filter = params.get("status")
            sql = (
                "SELECT t.id, t.prompt, t.interval_seconds, t.status, "
                "t.last_executed_at, t.allowed_tools "
                "FROM agentic_tasks t "
                "WHERE t.agent_id = ?"
            )
            sql_params: list = [agent_id]
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

        elif action == "register_slack_thread":
            channel_id = params.get("channel_id", "")
            thread_ts = params.get("thread_ts", "")
            if not channel_id or not thread_ts:
                return {"request_id": request_id, "status": "error", "error": "channel_id and thread_ts are required"}
            row_id = str(uuid.uuid4())
            try:
                await db.execute(
                    "INSERT INTO slack_active_threads "
                    "(id, channel_id, thread_ts, agent_id, last_ts) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (row_id, channel_id, thread_ts, agent_id, thread_ts),
                )
                await db.commit()
            except IntegrityError:
                # UNIQUE constraint — already monitoring
                return {
                    "request_id": request_id,
                    "status": "ok",
                    "data": {"already_registered": True, "channel_id": channel_id, "thread_ts": thread_ts},
                }
            logger.info("Registered slack thread %s/%s for agent %s", channel_id, thread_ts, agent_id[:8])
            return {
                "request_id": request_id,
                "status": "ok",
                "data": {"registered": True, "channel_id": channel_id, "thread_ts": thread_ts},
            }

        elif action == "unregister_slack_thread":
            channel_id = params.get("channel_id", "")
            thread_ts = params.get("thread_ts", "")
            if not channel_id or not thread_ts:
                return {"request_id": request_id, "status": "error", "error": "channel_id and thread_ts are required"}
            cursor = await db.execute(
                "DELETE FROM slack_active_threads "
                "WHERE channel_id = ? AND thread_ts = ? AND agent_id = ?",
                (channel_id, thread_ts, agent_id),
            )
            await db.commit()
            if cursor.rowcount == 0:
                return {"request_id": request_id, "status": "error", "error": "Thread not found"}
            logger.info("Unregistered slack thread %s/%s for agent %s", channel_id, thread_ts, agent_id[:8])
            return {
                "request_id": request_id,
                "status": "ok",
                "data": {"unregistered": True, "channel_id": channel_id, "thread_ts": thread_ts},
            }

        elif action == "list_slack_threads":
            async with db.execute(
                "SELECT id, channel_id, thread_ts, last_ts, created_at "
                "FROM slack_active_threads WHERE agent_id = ?",
                (agent_id,),
            ) as cur:
                rows = await cur.fetchall()
            threads = [
                {
                    "id": r[0],
                    "channel_id": r[1],
                    "thread_ts": r[2],
                    "last_ts": r[3],
                    "created_at": r[4],
                }
                for r in rows
            ]
            return {"request_id": request_id, "status": "ok", "data": {"threads": threads}}

        elif action == "mcp_call":
            tool_name = params.get("tool_name", "")
            server_name = params.get("server_name", "")
            arguments = params.get("arguments", {})

            # Permission gate for gh CLI tool
            if server_name == "github" and tool_name == "gh":
                from orchestrator.gh_permissions import GhPermission, classify_gh_command

                command = arguments.get("command", "")
                permission, matched = classify_gh_command(command)

                if permission == GhPermission.DENIED:
                    return {
                        "request_id": request_id,
                        "status": "ok",
                        "data": {
                            "content": [{"type": "text", "text": f"Command not allowed: '{matched}' is not in the approved command list."}],
                            "isError": True,
                        },
                    }

                if permission == GhPermission.NEEDS_APPROVAL:
                    if not approval_manager or not ws_manager:
                        return {
                            "request_id": request_id,
                            "status": "ok",
                            "data": {
                                "content": [{"type": "text", "text": f"Command requires approval but no approval channel available: gh {command}"}],
                                "isError": True,
                            },
                        }
                    approved = await approval_manager.request_approval(
                        request_id, agent_id, command, ws_manager,
                    )
                    if not approved:
                        return {
                            "request_id": request_id,
                            "status": "ok",
                            "data": {
                                "content": [{"type": "text", "text": f"User denied execution of: gh {command}"}],
                                "isError": False,
                            },
                        }

            # Permission gate for git_push tool
            if server_name == "github" and tool_name == "git_push":
                if not approval_manager or not ws_manager:
                    return {
                        "request_id": request_id,
                        "status": "ok",
                        "data": {
                            "content": [{"type": "text", "text": "git_push requires approval but no approval channel available"}],
                            "isError": True,
                        },
                    }
                desc = f"git push {arguments.get('repo_path', '')} → {arguments.get('remote', 'origin')} {arguments.get('branch', '(current)')}"
                approved = await approval_manager.request_approval(
                    request_id, agent_id, desc, ws_manager,
                )
                if not approved:
                    return {
                        "request_id": request_id,
                        "status": "ok",
                        "data": {
                            "content": [{"type": "text", "text": f"User denied: {desc}"}],
                            "isError": False,
                        },
                    }

            if not mcp_manager:
                return {
                    "request_id": request_id,
                    "status": "error",
                    "error": "No MCP servers configured for this agent",
                }

            try:
                result = await mcp_manager.call_tool(tool_name, arguments)
                return {
                    "request_id": request_id,
                    "status": "ok",
                    "data": result,
                }
            except Exception as e:
                logger.exception("MCP tool call failed: %s/%s", server_name, tool_name)
                return {
                    "request_id": request_id,
                    "status": "error",
                    "error": f"MCP tool {server_name}/{tool_name} failed: {e}",
                }

        else:
            return {"request_id": request_id, "status": "error", "error": f"Unknown action: {action}"}

    except Exception as e:
        logger.exception("Error handling tool request %s", action)
        return {"request_id": request_id, "status": "error", "error": str(e)}


async def _get_initial_snapshot(agent_id: str, watch_dir: str) -> list[str]:
    """Get current file listing for a watch directory at task creation time."""
    db = await get_db()
    async with db.execute(
        "SELECT host_dir FROM agents WHERE id = ?", (agent_id,),
    ) as cur:
        row = await cur.fetchone()
    if not row:
        return []

    host_dir = Path(row[0])
    target = host_dir / watch_dir

    try:
        target = target.resolve()
        if not target.is_relative_to(host_dir.resolve()):
            return []
    except (ValueError, OSError):
        return []

    if not target.is_dir():
        return []

    IPC_FILES = {"input.json", "output.json", "request.json", "response.json"}
    result = []
    try:
        for entry in target.iterdir():
            if entry.is_file() and entry.name not in IPC_FILES and not entry.name.endswith(".log"):
                result.append(entry.name)
    except OSError:
        pass
    return sorted(result)


async def _schedule_compaction_task(agent_id: str, date: str) -> None:
    """Insert a memory_compaction scheduled task for the given agent."""
    db = await get_db()
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


async def _send_queue_status(ws_mgr: WebSocketManager, agent_id: str) -> None:
    counts = await get_queue_counts(agent_id)
    frame = QueueStatusFrame(**counts)
    await ws_mgr.send(frame.model_dump_json())


# --- Polling loop ---


async def _handle_request_background(
    agent_id: str,
    request: dict,
    response_path: Path,
    mcp_manager: McpServerManager | None,
    ws_manager: WebSocketManager | None = None,
    approval_manager: GhApprovalManager | None = None,
) -> None:
    """Handle a tool request from the worker in the background."""
    try:
        result = await _handle_tool_request(
            agent_id, request, mcp_manager, ws_manager, approval_manager,
        )
        atomic_write(response_path, json.dumps(result).encode())
    except Exception:
        logger.exception("Background request handler failed for agent %s", agent_id)
        error_result = {
            "request_id": request.get("request_id", ""),
            "status": "error",
            "error": "Internal error handling request",
        }
        try:
            atomic_write(response_path, json.dumps(error_result).encode())
        except OSError:
            logger.exception("Failed to write error response for agent %s", agent_id)


async def _process_output(
    output_path: Path,
    agent_id: str,
    ws_mgr: WebSocketManager,
) -> None:
    """Read output.json and forward events to DB + WebSocket."""
    if not output_path.exists():
        return
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
        return

    notified: set[str] = set()
    for event in events:
        try:
            msg_id = event.get("message_id", "")
            source_meta = _inflight_source.get(msg_id)
            row_id = await _process_event(
                event, agent_id, ws_mgr, source_meta,
            )
            if row_id:
                notified.add(row_id)
            if event.get("type") == "complete" and msg_id:
                _inflight_source.pop(msg_id, None)
        except Exception:
            logger.exception(
                "Error processing output event for agent %s",
                agent_id,
            )

    db = await get_db()

    # Update last_activity so the idle reaper knows the worker is alive.
    # Without this, long-running agent work (many tool calls) looks
    # "inactive" and the reaper kills the container prematurely.
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    await db.execute(
        "UPDATE agent_containers SET last_activity = ? "
        "WHERE agent_id = ? AND status IN ('running', 'idle')",
        (now, agent_id),
    )
    await db.commit()
    for row_id in notified:
        msg_data = None
        try:
            async with db.execute(
                "SELECT id, role, content, created_at, metadata, status "
                "FROM messages WHERE id = ?",
                (row_id,),
            ) as cur:
                msg_row = await cur.fetchone()
            if msg_row:
                msg_data = {
                    "id": msg_row[0],
                    "role": msg_row[1],
                    "content": msg_row[2],
                    "created_at": msg_row[3],
                    "metadata": msg_row[4],
                    "status": msg_row[5],
                }
        except SqliteError:
            logger.exception("Failed to read message %s for WS frame", row_id)

        payload: dict[str, typing.Any] = {
            "type": "message_updated",
            "message_id": row_id,
        }
        if msg_data:
            payload["message"] = msg_data
        await ws_mgr.send(json.dumps(payload))


async def _polling_loop(
    agent_id: str,
    host_dir: Path,
    ws_mgr: WebSocketManager,
    mcp_manager: McpServerManager | None = None,
    approval_manager: GhApprovalManager | None = None,
) -> None:
    input_path = host_dir / "input.json"
    output_path = host_dir / "output.json"
    request_path = host_dir / "request.json"
    response_path = host_dir / "response.json"
    db = await get_db()
    pending_request: asyncio.Task | None = None

    while True:
        await asyncio.sleep(0.5)
        try:
            # --- Input ACK: IN-FLIGHT messages + input.json gone = PROCESSED ---
            async with db.execute(
                "SELECT COUNT(*) FROM message_queue "
                "WHERE agent_id = ? AND status = 'IN-FLIGHT'",
                (agent_id,),
            ) as cur:
                row = await cur.fetchone()
                in_flight_count = row[0]

            if in_flight_count > 0 and not input_path.exists():
                await db.execute(
                    "DELETE FROM message_queue "
                    "WHERE agent_id = ? AND status = 'IN-FLIGHT'",
                    (agent_id,),
                )
                await db.commit()
                await _send_queue_status(ws_mgr, agent_id)

            # --- Input flush: QUEUED messages + no input.json = write input.json ---
            async with db.execute(
                "SELECT id, payload FROM message_queue "
                "WHERE agent_id = ? AND status = 'QUEUED' "
                "ORDER BY created_at",
                (agent_id,),
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
                    "WHERE agent_id = ? AND status IN ('running', 'idle')",
                    (now, agent_id),
                )
                await db.commit()
                await _send_queue_status(ws_mgr, agent_id)

            # --- Output polling FIRST: always forward events before handling requests ---
            await _process_output(output_path, agent_id, ws_mgr)

            # --- Request polling: handle tool requests in background ---
            if request_path.exists():
                if pending_request and not pending_request.done():
                    pass
                else:
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
                        pending_request = asyncio.create_task(
                            _handle_request_background(
                                agent_id, request, response_path,
                                mcp_manager, ws_mgr, approval_manager,
                            ),
                            name=f"req-{agent_id[:8]}",
                        )

        except (ConnectionError, RuntimeError):
            # WebSocket disconnected
            break
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Polling loop error for agent %s", agent_id)


def start_polling_loop(
    agent_id: str,
    host_dir: Path,
    ws_mgr: WebSocketManager,
    mcp_manager: McpServerManager | None = None,
    approval_manager: GhApprovalManager | None = None,
) -> asyncio.Task:
    return asyncio.create_task(
        _polling_loop(agent_id, host_dir, ws_mgr, mcp_manager, approval_manager),
        name=f"poll-{agent_id[:8]}",
    )
