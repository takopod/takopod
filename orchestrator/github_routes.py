"""GitHub integration API routes.

Uses the ``gh`` CLI for authentication — no PAT management needed.
Provides per-agent enablement toggle.
"""

from __future__ import annotations

import asyncio
import logging
import shutil

from fastapi import APIRouter, HTTPException

from orchestrator.db import get_db
from orchestrator.models import GitHubAgentToggle

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/github/config")
async def get_github_config():
    """Check gh CLI availability and auth status."""
    if not shutil.which("gh"):
        return {"configured": False, "gh_installed": False, "error": "gh CLI is not installed."}

    try:
        proc = await asyncio.create_subprocess_exec(
            "gh", "auth", "status",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        output = (stdout or stderr).decode().strip()

        if proc.returncode != 0:
            return {
                "configured": False,
                "gh_installed": True,
                "error": "Not authenticated. Run 'gh auth login' in your terminal.",
                "status_output": output,
            }

        username = ""
        try:
            proc_json = await asyncio.create_subprocess_exec(
                "gh", "api", "user", "--jq", ".login",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            out, _ = await asyncio.wait_for(proc_json.communicate(), timeout=10)
            if proc_json.returncode == 0:
                username = out.decode().strip()
        except Exception:
            pass

        return {
            "configured": True,
            "gh_installed": True,
            "username": username,
            "status_output": output,
        }
    except Exception as exc:
        return {"configured": False, "gh_installed": True, "error": str(exc)}


# --- Per-Agent GitHub Toggle ---


@router.get("/agents/{agent_id}/github")
async def get_agent_github(agent_id: str):
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
        "WHERE ams.agent_id = ? AND ms.name = 'github'",
        (agent_id,),
    ) as cur:
        row = await cur.fetchone()
    return {"enabled": bool(row[0]) if row else False}


@router.put("/agents/{agent_id}/github")
async def put_agent_github(agent_id: str, req: GitHubAgentToggle):
    db = await get_db()
    async with db.execute(
        "SELECT id FROM agents WHERE id = ? AND status = 'active'",
        (agent_id,),
    ) as cur:
        if not await cur.fetchone():
            raise HTTPException(status_code=404, detail="Agent not found")

    async with db.execute(
        "SELECT id FROM mcp_servers WHERE name = 'github' AND builtin = 1",
    ) as cur:
        srv = await cur.fetchone()
    if not srv:
        raise HTTPException(status_code=404, detail="GitHub integration not available (is gh CLI installed?)")

    await db.execute(
        "INSERT INTO agent_mcp_servers (agent_id, mcp_server_id, enabled) "
        "VALUES (?, ?, ?) "
        "ON CONFLICT(agent_id, mcp_server_id) DO UPDATE SET enabled = excluded.enabled",
        (agent_id, srv[0], 1 if req.enabled else 0),
    )
    await db.commit()
    return {"enabled": req.enabled}
