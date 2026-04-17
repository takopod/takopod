"""Google Workspace (GWS) integration API routes.

Global credential management and per-agent enablement toggle.
Uses the external_tools table instead of MCP servers.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
import uuid

from fastapi import APIRouter, HTTPException

from orchestrator.db import get_db
from orchestrator.models import GWSAgentToggle, GWSConfigRequest

logger = logging.getLogger(__name__)

router = APIRouter()

GWS_TOOL_NAME = "gws"


async def _get_gws_tool(db) -> tuple[str, str] | None:
    """Return (id, config) for the gws external tool, or None."""
    async with db.execute(
        "SELECT id, config FROM external_tools WHERE name = ?",
        (GWS_TOOL_NAME,),
    ) as cur:
        return await cur.fetchone()


def _extract_user_email(credentials_json: str) -> str:
    """Try to extract user email from GWS credentials JSON."""
    try:
        creds = json.loads(credentials_json)
        return creds.get("user_email", "") or creds.get("email", "")
    except (json.JSONDecodeError, TypeError):
        return ""


def _refresh_access_token(creds: dict) -> str | None:
    """Exchange a refresh token for a fresh access token. Returns None on failure."""
    refresh_token = creds.get("refresh_token", "")
    client_id = creds.get("client_id", "")
    client_secret = creds.get("client_secret", "")
    if not (refresh_token and client_id and client_secret):
        return None

    body = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
        "client_secret": client_secret,
    }).encode()
    req = urllib.request.Request(
        "https://oauth2.googleapis.com/token",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            return data.get("access_token")
    except Exception:
        return None


# --- Global GWS Config ---


@router.get("/gws/config")
async def get_gws_config():
    db = await get_db()
    row = await _get_gws_tool(db)
    if not row:
        return {"configured": False}

    try:
        config = json.loads(row[1])
    except (json.JSONDecodeError, TypeError):
        return {"configured": False}

    result: dict = {"configured": True}
    if config.get("user_email"):
        result["user_email"] = config["user_email"]
    if config.get("credentials_json"):
        result["credentials"] = "configured"
    return result


@router.put("/gws/config")
async def put_gws_config(req: GWSConfigRequest):
    user_email = _extract_user_email(req.credentials_json)

    config = json.dumps({
        "credentials_json": req.credentials_json,
        "user_email": user_email,
    })

    db = await get_db()
    row = await _get_gws_tool(db)

    if row:
        await db.execute(
            "UPDATE external_tools SET config = ? WHERE name = ?",
            (config, GWS_TOOL_NAME),
        )
    else:
        tool_id = str(uuid.uuid4())
        await db.execute(
            "INSERT INTO external_tools (id, name, config, builtin) VALUES (?, ?, ?, 1)",
            (tool_id, GWS_TOOL_NAME, config),
        )
    await db.commit()

    result: dict = {"configured": True}
    if user_email:
        result["user_email"] = user_email
    return result


@router.delete("/gws/config")
async def delete_gws_config():
    db = await get_db()
    await db.execute(
        "DELETE FROM external_tools WHERE name = ?",
        (GWS_TOOL_NAME,),
    )
    await db.commit()
    return {"configured": False}


@router.get("/gws/status")
async def get_gws_status():
    """Test GWS credentials by making a real API call to Google."""
    db = await get_db()
    row = await _get_gws_tool(db)
    if not row:
        return {"connected": False, "error": "No GWS credentials configured."}

    try:
        config = json.loads(row[1])
    except (json.JSONDecodeError, TypeError):
        return {"connected": False, "error": "Invalid GWS configuration."}

    creds_raw = config.get("credentials_json", "")
    if not creds_raw:
        return {"connected": False, "error": "No GWS credentials configured."}

    try:
        creds = json.loads(creds_raw)
    except (json.JSONDecodeError, TypeError):
        return {"connected": False, "error": "Invalid credentials JSON."}

    access_token = creds.get("access_token", "")

    # If no access token or it might be expired, try refreshing
    if not access_token:
        access_token = _refresh_access_token(creds)
        if not access_token:
            return {"connected": False, "error": "Could not obtain access token. Check that credentials include refresh_token, client_id, and client_secret."}

    try:
        req = urllib.request.Request(
            "https://www.googleapis.com/oauth2/v1/userinfo?alt=json",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            user_email = data.get("email", "")
            if user_email and user_email != config.get("user_email"):
                config["user_email"] = user_email
                await db.execute(
                    "UPDATE external_tools SET config = ? WHERE name = ?",
                    (json.dumps(config), GWS_TOOL_NAME),
                )
                await db.commit()
            return {
                "connected": True,
                "user_email": user_email,
            }
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            # Access token expired, try refreshing
            refreshed = _refresh_access_token(creds)
            if refreshed:
                try:
                    req2 = urllib.request.Request(
                        "https://www.googleapis.com/oauth2/v1/userinfo?alt=json",
                        headers={"Authorization": f"Bearer {refreshed}"},
                    )
                    with urllib.request.urlopen(req2, timeout=10) as resp2:
                        data = json.loads(resp2.read().decode())
                        user_email = data.get("email", "")
                        if user_email and user_email != config.get("user_email"):
                            config["user_email"] = user_email
                            await db.execute(
                                "UPDATE external_tools SET config = ? WHERE name = ?",
                                (json.dumps(config), GWS_TOOL_NAME),
                            )
                            await db.commit()
                        return {
                            "connected": True,
                            "user_email": user_email,
                        }
                except Exception:
                    pass
        try:
            detail = json.loads(exc.read().decode()).get("error", {}).get("message", exc.reason)
        except Exception:
            detail = exc.reason
        return {"connected": False, "error": f"Google API error ({exc.code}): {detail}"}
    except Exception as exc:
        return {"connected": False, "error": str(exc)}


# --- Per-Agent GWS Toggle ---


@router.get("/agents/{agent_id}/gws")
async def get_agent_gws(agent_id: str):
    db = await get_db()
    async with db.execute(
        "SELECT id FROM agents WHERE id = ? AND status = 'active'",
        (agent_id,),
    ) as cur:
        if not await cur.fetchone():
            raise HTTPException(status_code=404, detail="Agent not found")

    async with db.execute(
        "SELECT aet.enabled FROM agent_external_tools aet "
        "JOIN external_tools et ON et.id = aet.external_tool_id "
        "WHERE aet.agent_id = ? AND et.name = ?",
        (agent_id, GWS_TOOL_NAME),
    ) as cur:
        row = await cur.fetchone()
    return {"enabled": bool(row[0]) if row else False}


@router.put("/agents/{agent_id}/gws")
async def put_agent_gws(agent_id: str, req: GWSAgentToggle):
    db = await get_db()
    async with db.execute(
        "SELECT id FROM agents WHERE id = ? AND status = 'active'",
        (agent_id,),
    ) as cur:
        if not await cur.fetchone():
            raise HTTPException(status_code=404, detail="Agent not found")

    tool_row = await _get_gws_tool(db)
    if not tool_row:
        raise HTTPException(status_code=404, detail="GWS integration not configured")

    tool_id = tool_row[0]
    await db.execute(
        "INSERT INTO agent_external_tools (agent_id, external_tool_id, enabled) "
        "VALUES (?, ?, ?) "
        "ON CONFLICT(agent_id, external_tool_id) DO UPDATE SET enabled = excluded.enabled",
        (agent_id, tool_id, 1 if req.enabled else 0),
    )
    await db.commit()
    return {"enabled": req.enabled}
