"""Slack integration API routes.

Global credential management and per-agent enablement toggle.
Kept in a separate file to avoid entangling with the main routes.py.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException

from orchestrator.db import get_db
from orchestrator.models import SlackAgentToggle, SlackConfigRequest

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
