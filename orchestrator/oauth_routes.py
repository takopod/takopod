"""OAuth API routes for HTTP MCP server authorization."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

from orchestrator.db import get_db
from orchestrator.oauth import FileTokenStorage, flow_manager

logger = logging.getLogger(__name__)

router = APIRouter()


async def _get_server_url(server_name: str) -> str:
    """Look up the URL for an HTTP MCP server from the database."""
    db = await get_db()
    async with db.execute(
        "SELECT transport, url FROM mcp_servers WHERE name = ?",
        (server_name,),
    ) as cur:
        row = await cur.fetchone()
    if not row:
        raise HTTPException(
            status_code=404, detail=f"Server '{server_name}' not found",
        )
    if row[0] != "http":
        raise HTTPException(
            status_code=400,
            detail=f"Server '{server_name}' is not an HTTP transport server",
        )
    if not row[1]:
        raise HTTPException(
            status_code=400,
            detail=f"Server '{server_name}' has no URL configured",
        )
    return row[1]


@router.get("/oauth/start/{server_name}")
async def start_oauth(server_name: str):
    """Initiate OAuth flow for an HTTP MCP server."""
    server_url = await _get_server_url(server_name)
    try:
        authorize_url = await flow_manager.start_flow(server_name, server_url)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {"authorize_url": authorize_url}


@router.get("/oauth/callback")
async def oauth_callback(code: str, state: str):
    """Receive OAuth redirect from the authorization server."""
    server_name = flow_manager.complete_flow(code, state)
    if not server_name:
        raise HTTPException(
            status_code=400,
            detail="Unknown or expired OAuth flow state",
        )
    return HTMLResponse(
        content=(
            "<!DOCTYPE html><html><head><title>Authorization Complete</title></head>"
            "<body style='font-family:system-ui;display:flex;align-items:center;"
            "justify-content:center;height:100vh;margin:0;background:#0a0a0a;color:#fafafa'>"
            "<div style='text-align:center'>"
            "<h2>Authorization Complete</h2>"
            f"<p>MCP server <strong>{server_name}</strong> has been authorized.</p>"
            "<p style='color:#888'>You can close this tab.</p>"
            "</div></body></html>"
        ),
        status_code=200,
    )


@router.get("/oauth/status/{server_name}")
async def oauth_status(server_name: str):
    """Check if valid OAuth tokens exist for a server."""
    storage = FileTokenStorage(server_name)
    return {"authorized": storage.has_tokens(), "server_name": server_name}


@router.delete("/oauth/tokens/{server_name}")
async def delete_oauth_tokens(server_name: str):
    """Delete stored OAuth tokens for a server."""
    storage = FileTokenStorage(server_name)
    storage.delete()
    return {"authorized": False, "server_name": server_name}
