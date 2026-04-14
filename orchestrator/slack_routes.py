"""Slack integration API routes.

Global credential management and per-agent enablement toggle.
Kept in a separate file to avoid entangling with the main routes.py.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from sqlite3 import IntegrityError

from fastapi import APIRouter, HTTPException

from orchestrator.db import get_db
from orchestrator.models import (
    SlackAgentToggle,
    SlackConfigRequest,
    SlackPollingChannelRequest,
    SlackPollingChannelUpdate,
    SlackPollingToggle,
    SlackThreadRequest,
)
from orchestrator.settings import get_setting, set_setting

logger = logging.getLogger(__name__)

router = APIRouter()

SLACK_CONFIG_PATH = Path("data/slack-config.json")


def _read_slack_config() -> dict | None:
    """Read the global Slack config from disk, or None if not configured."""
    if not SLACK_CONFIG_PATH.is_file():
        return None
    try:
        return json.loads(SLACK_CONFIG_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _mask_token(token: str) -> str:
    """Mask a token, showing only the first 8 and last 4 characters."""
    if len(token) <= 12:
        return "****"
    return f"{token[:8]}...{token[-4:]}"


# --- Global Slack Config ---


@router.get("/slack/config")
async def get_slack_config():
    config = _read_slack_config()
    if not config:
        return {"configured": False}
    return {
        "configured": True,
        "xoxc_token": _mask_token(config.get("xoxc_token", "")),
        "d_cookie": _mask_token(config.get("d_cookie", "")),
        "member_id": config.get("member_id", ""),
    }


@router.put("/slack/config")
async def put_slack_config(req: SlackConfigRequest):
    SLACK_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    data = req.model_dump()
    SLACK_CONFIG_PATH.write_text(json.dumps(data, indent=2))

    from orchestrator.mcp_seed import seed_builtin_mcp_servers
    db = await get_db()
    await seed_builtin_mcp_servers(db)

    return {
        "configured": True,
        "xoxc_token": _mask_token(data["xoxc_token"]),
        "d_cookie": _mask_token(data["d_cookie"]),
        "member_id": data["member_id"],
    }


@router.delete("/slack/config")
async def delete_slack_config():
    if SLACK_CONFIG_PATH.is_file():
        SLACK_CONFIG_PATH.unlink()

    from orchestrator.mcp_seed import seed_builtin_mcp_servers
    db = await get_db()
    await seed_builtin_mcp_servers(db)

    return {"configured": False}


@router.get("/slack/status")
async def get_slack_status():
    """Test the Slack connection using the stored credentials."""
    config = _read_slack_config()
    if not config:
        return {"connected": False, "error": "No Slack credentials configured."}

    try:
        from slack_sdk import WebClient

        client = WebClient(
            token=config["xoxc_token"],
            headers={"Cookie": f"d={config['d_cookie']}"},
        )
        response = client.auth_test()
        return {
            "connected": True,
            "team": response.get("team"),
            "user": response.get("user"),
        }
    except Exception as e:
        return {"connected": False, "error": str(e)}


# --- Per-Agent Slack Toggle ---


@router.get("/agents/{agent_id}/slack")
async def get_agent_slack(agent_id: str):
    db = await get_db()
    async with db.execute(
        "SELECT id FROM agents WHERE id = ? AND status = 'active'",
        (agent_id,),
    ) as cur:
        if not await cur.fetchone():
            raise HTTPException(status_code=404, detail="Agent not found")

    async with db.execute(
        "SELECT ams.enabled FROM agent_mcp_servers ams "
        "JOIN mcp_servers ms ON ms.id = ams.mcp_server_id "
        "WHERE ams.agent_id = ? AND ms.name = 'slack'",
        (agent_id,),
    ) as cur:
        row = await cur.fetchone()
    return {"enabled": bool(row[0]) if row else False}


@router.put("/agents/{agent_id}/slack")
async def put_agent_slack(agent_id: str, req: SlackAgentToggle):
    db = await get_db()
    async with db.execute(
        "SELECT id FROM agents WHERE id = ? AND status = 'active'",
        (agent_id,),
    ) as cur:
        if not await cur.fetchone():
            raise HTTPException(status_code=404, detail="Agent not found")

    # Look up the slack MCP server
    async with db.execute(
        "SELECT id FROM mcp_servers WHERE name = 'slack' AND builtin = 1",
    ) as cur:
        srv = await cur.fetchone()
    if not srv:
        raise HTTPException(status_code=404, detail="Slack integration not configured")

    # Upsert into agent_mcp_servers
    await db.execute(
        "INSERT INTO agent_mcp_servers (agent_id, mcp_server_id, enabled) "
        "VALUES (?, ?, ?) "
        "ON CONFLICT(agent_id, mcp_server_id) DO UPDATE SET enabled = excluded.enabled",
        (agent_id, srv[0], 1 if req.enabled else 0),
    )
    await db.commit()
    return {"enabled": req.enabled}


# --- Slack Channel Polling ---


@router.get("/slack/polling")
async def get_slack_polling():
    """Return global polling toggle and list of configured channels."""
    db = await get_db()
    enabled = (await get_setting("slack_polling_enabled", "false")) == "true"
    async with db.execute(
        "SELECT id, channel_id, channel_name, interval_seconds, enabled, last_ts, created_at "
        "FROM slack_polling_channels ORDER BY created_at",
    ) as cur:
        rows = await cur.fetchall()
    channels = [
        {
            "id": r[0],
            "channel_id": r[1],
            "channel_name": r[2],
            "interval_seconds": r[3],
            "enabled": bool(r[4]),
            "last_ts": r[5],
            "created_at": r[6],
        }
        for r in rows
    ]
    return {"enabled": enabled, "channels": channels}


@router.put("/slack/polling")
async def put_slack_polling(req: SlackPollingToggle):
    """Toggle global Slack polling on/off."""
    await set_setting(
        "slack_polling_enabled", "true" if req.enabled else "false",
    )
    return await get_slack_polling()


@router.post("/slack/polling/channels")
async def add_polling_channel(req: SlackPollingChannelRequest):
    """Add a channel to poll."""
    import time
    import uuid

    db = await get_db()
    row_id = str(uuid.uuid4())
    now_ts = f"{time.time():.6f}"
    try:
        await db.execute(
            "INSERT INTO slack_polling_channels "
            "(id, channel_id, channel_name, interval_seconds, last_ts) "
            "VALUES (?, ?, ?, ?, ?)",
            (row_id, req.channel_id, req.channel_name, req.interval_seconds, now_ts),
        )
        await db.commit()
    except IntegrityError:
        raise HTTPException(
            status_code=409, detail="Channel already added",
        )
    return await get_slack_polling()


@router.put("/slack/polling/channels/{channel_row_id}")
async def update_polling_channel(
    channel_row_id: str, req: SlackPollingChannelUpdate,
):
    """Update a polling channel's interval or enabled state."""
    db = await get_db()
    async with db.execute(
        "SELECT id FROM slack_polling_channels WHERE id = ?",
        (channel_row_id,),
    ) as cur:
        if not await cur.fetchone():
            raise HTTPException(status_code=404, detail="Channel not found")

    if req.interval_seconds is not None:
        await db.execute(
            "UPDATE slack_polling_channels SET interval_seconds = ? WHERE id = ?",
            (req.interval_seconds, channel_row_id),
        )
    if req.enabled is not None:
        await db.execute(
            "UPDATE slack_polling_channels SET enabled = ? WHERE id = ?",
            (1 if req.enabled else 0, channel_row_id),
        )
    await db.commit()
    return await get_slack_polling()


@router.delete("/slack/polling/channels/{channel_row_id}")
async def delete_polling_channel(channel_row_id: str):
    """Remove a channel from polling."""
    db = await get_db()
    await db.execute(
        "DELETE FROM slack_polling_channels WHERE id = ?",
        (channel_row_id,),
    )
    await db.commit()
    return await get_slack_polling()


@router.get("/slack/channels")
async def list_slack_channels():
    """List Slack channels the authenticated user is a member of."""
    config = _read_slack_config()
    if not config:
        raise HTTPException(status_code=400, detail="Slack not configured")

    import asyncio

    from slack_sdk import WebClient

    client = WebClient(
        token=config["xoxc_token"],
        headers={"Cookie": f"d={config['d_cookie']}"},
    )
    try:
        response = await asyncio.to_thread(
            client.conversations_list,
            types="public_channel,private_channel",
            exclude_archived=True,
            limit=200,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))

    channels = [
        {
            "id": ch["id"],
            "name": ch["name"],
            "is_private": ch.get("is_private", False),
        }
        for ch in response.get("channels", [])
        if ch.get("is_member")
    ]
    return {"channels": channels}


# --- Slack Active Threads ---


@router.get("/slack/threads")
async def get_active_threads():
    """Return all active threads being monitored."""
    db = await get_db()
    async with db.execute(
        "SELECT t.id, t.channel_id, t.thread_ts, t.agent_id, t.last_ts, "
        "t.created_at, a.name AS agent_name "
        "FROM slack_active_threads t "
        "LEFT JOIN agents a ON a.id = t.agent_id "
        "ORDER BY t.created_at",
    ) as cur:
        rows = await cur.fetchall()
    threads = [
        {
            "id": r[0],
            "channel_id": r[1],
            "thread_ts": r[2],
            "agent_id": r[3],
            "last_ts": r[4],
            "created_at": r[5],
            "agent_name": r[6],
        }
        for r in rows
    ]
    return {"threads": threads}


@router.post("/slack/threads")
async def add_active_thread(req: SlackThreadRequest):
    """Add a thread to monitor for a specific agent."""
    import uuid

    db = await get_db()

    # Verify agent exists
    async with db.execute(
        "SELECT id FROM agents WHERE id = ? AND status = 'active'",
        (req.agent_id,),
    ) as cur:
        if not await cur.fetchone():
            raise HTTPException(status_code=404, detail="Agent not found")

    row_id = str(uuid.uuid4())
    try:
        await db.execute(
            "INSERT INTO slack_active_threads "
            "(id, channel_id, thread_ts, agent_id, last_ts) "
            "VALUES (?, ?, ?, ?, ?)",
            (row_id, req.channel_id, req.thread_ts, req.agent_id, req.thread_ts),
        )
        await db.commit()
    except IntegrityError:
        raise HTTPException(
            status_code=409,
            detail="This agent is already monitoring this thread",
        )
    return await get_active_threads()


@router.delete("/slack/threads/{thread_row_id}")
async def delete_active_thread(thread_row_id: str):
    """Stop monitoring a thread."""
    db = await get_db()
    cursor = await db.execute(
        "DELETE FROM slack_active_threads WHERE id = ?",
        (thread_row_id,),
    )
    await db.commit()
    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="Thread not found")
    return await get_active_threads()
