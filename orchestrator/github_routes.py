"""GitHub integration API routes.

Global credential management and per-agent enablement toggle.
Mirrors the Slack integration pattern in slack_routes.py.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from pathlib import Path

from fastapi import APIRouter, HTTPException

from orchestrator.db import get_db
from orchestrator.models import GitHubAgentToggle, GitHubConfigRequest

logger = logging.getLogger(__name__)

router = APIRouter()

GITHUB_CONFIG_PATH = Path("data/github-config.json")


def _read_github_config() -> dict | None:
    """Read the global GitHub config from disk, or None if not configured."""
    if not GITHUB_CONFIG_PATH.is_file():
        return None
    try:
        return json.loads(GITHUB_CONFIG_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _mask_token(token: str) -> str:
    """Mask a token, showing only the first 8 and last 4 characters."""
    if len(token) <= 12:
        return "****"
    return f"{token[:8]}...{token[-4:]}"


# --- Global GitHub Config ---


@router.get("/github/config")
async def get_github_config():
    config = _read_github_config()
    if not config:
        return {"configured": False}
    return {
        "configured": True,
        "personal_access_token": _mask_token(config.get("personal_access_token", "")),
    }


@router.put("/github/config")
async def put_github_config(req: GitHubConfigRequest):
    GITHUB_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    data = req.model_dump()

    # Resolve and cache the GitHub username for this token
    username = ""
    try:
        api_req = urllib.request.Request(
            "https://api.github.com/user",
            headers={
                "Authorization": f"Bearer {data['personal_access_token']}",
                "Accept": "application/vnd.github+json",
            },
        )
        with urllib.request.urlopen(api_req, timeout=10) as resp:
            username = json.loads(resp.read().decode()).get("login", "")
    except Exception:
        pass
    data["username"] = username

    GITHUB_CONFIG_PATH.write_text(json.dumps(data, indent=2))
    return {
        "configured": True,
        "personal_access_token": _mask_token(data["personal_access_token"]),
        "username": username,
    }


@router.delete("/github/config")
async def delete_github_config():
    if GITHUB_CONFIG_PATH.is_file():
        GITHUB_CONFIG_PATH.unlink()
    return {"configured": False}


@router.get("/github/status")
async def get_github_status():
    """Test the GitHub connection using the stored token."""
    config = _read_github_config()
    if not config:
        return {"connected": False, "error": "No GitHub token configured."}

    token = config.get("personal_access_token", "")
    if not token:
        return {"connected": False, "error": "No GitHub token configured."}

    try:
        req = urllib.request.Request(
            "https://api.github.com/user",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
            },
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            scopes = resp.headers.get("X-OAuth-Scopes", "")
            return {
                "connected": True,
                "username": data.get("login", ""),
                "scopes": scopes,
            }
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode()).get("message", exc.reason)
        except Exception:
            detail = exc.reason
        return {"connected": False, "error": f"GitHub API error ({exc.code}): {detail}"}
    except Exception as exc:
        return {"connected": False, "error": str(exc)}


# --- Per-Agent GitHub Toggle ---


@router.get("/agents/{agent_id}/github")
async def get_agent_github(agent_id: str):
    db = await get_db()
    async with db.execute(
        "SELECT github_enabled FROM agents WHERE id = ? AND status = 'active'",
        (agent_id,),
    ) as cur:
        row = await cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Agent not found")
    return {"enabled": bool(row[0])}


@router.put("/agents/{agent_id}/github")
async def put_agent_github(agent_id: str, req: GitHubAgentToggle):
    db = await get_db()
    async with db.execute(
        "SELECT id FROM agents WHERE id = ? AND status = 'active'",
        (agent_id,),
    ) as cur:
        row = await cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Agent not found")

    await db.execute(
        "UPDATE agents SET github_enabled = ? WHERE id = ?",
        (1 if req.enabled else 0, agent_id),
    )
    await db.commit()
    return {"enabled": req.enabled}
