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
        "SELECT slack_enabled FROM agents WHERE id = ? AND status = 'active'",
        (agent_id,),
    ) as cur:
        row = await cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Agent not found")
    return {"enabled": bool(row[0])}


@router.put("/agents/{agent_id}/slack")
async def put_agent_slack(agent_id: str, req: SlackAgentToggle):
    db = await get_db()
    async with db.execute(
        "SELECT id FROM agents WHERE id = ? AND status = 'active'",
        (agent_id,),
    ) as cur:
        row = await cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Agent not found")

    await db.execute(
        "UPDATE agents SET slack_enabled = ? WHERE id = ?",
        (1 if req.enabled else 0, agent_id),
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
    import uuid

    db = await get_db()
    row_id = str(uuid.uuid4())
    try:
        await db.execute(
            "INSERT INTO slack_polling_channels "
            "(id, channel_id, channel_name, interval_seconds) "
            "VALUES (?, ?, ?, ?)",
            (row_id, req.channel_id, req.channel_name, req.interval_seconds),
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
