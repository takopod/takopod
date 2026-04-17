"""Orchestrator-driven approval flow for gh CLI commands.

When a gh command requires human approval, the orchestrator pauses the IPC
tool call, sends a WebSocket frame to the frontend with Accept/Deny buttons,
and blocks on an asyncio.Future until the user responds or the timeout expires.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid

from orchestrator.db import get_db
from orchestrator.ws_manager import WebSocketManager

logger = logging.getLogger(__name__)

APPROVAL_TIMEOUT = 300.0  # 5 minutes


class GhApprovalManager:
    """Manages pending gh command approval requests."""

    def __init__(self) -> None:
        self._pending: dict[str, asyncio.Future[bool]] = {}
        self._metadata: dict[str, dict] = {}

    async def request_approval(
        self,
        request_id: str,
        agent_id: str,
        command: str,
        ws_manager: WebSocketManager,
    ) -> bool:
        """Request human approval for a gh command.

        Persists an approval message in the DB, sends a WebSocket frame to the
        frontend, and blocks until the user responds or the timeout expires.

        Returns True if approved, False if denied or timed out.
        """
        if not ws_manager.connected:
            logger.warning(
                "No WebSocket connection for agent %s — auto-denying gh %s",
                agent_id, command,
            )
            return False

        loop = asyncio.get_running_loop()
        future: asyncio.Future[bool] = loop.create_future()
        self._pending[request_id] = future
        self._metadata[request_id] = {
            "agent_id": agent_id,
            "command": command,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

        timestamp = self._metadata[request_id]["timestamp"]
        message_id = str(uuid.uuid4())

        await self._persist_approval_message(
            message_id, request_id, agent_id, command, "pending", timestamp,
        )

        await ws_manager.send(json.dumps({
            "type": "gh_approval_request",
            "request_id": request_id,
            "agent_id": agent_id,
            "command": command,
            "message_id": message_id,
            "timestamp": timestamp,
        }))

        try:
            approved = await asyncio.wait_for(future, timeout=APPROVAL_TIMEOUT)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            approved = False
        finally:
            self._pending.pop(request_id, None)
            self._metadata.pop(request_id, None)

        status = "approved" if approved else "denied"
        await self._update_approval_status(message_id, status)
        await ws_manager.send(json.dumps({
            "type": "message_updated",
            "message_id": message_id,
        }))

        return approved

    def resolve(self, request_id: str, approved: bool) -> None:
        """Resolve a pending approval (called by the WebSocket handler)."""
        future = self._pending.get(request_id)
        if future is None:
            logger.warning("No pending approval for request_id=%s", request_id)
            return
        if future.done():
            return
        future.set_result(approved)

    def cancel_all_for_agent(self, agent_id: str) -> None:
        """Cancel all pending approvals for an agent (on WS disconnect)."""
        to_cancel = [
            rid for rid, meta in self._metadata.items()
            if meta["agent_id"] == agent_id
        ]
        for rid in to_cancel:
            future = self._pending.get(rid)
            if future and not future.done():
                future.set_result(False)

    async def _persist_approval_message(
        self,
        message_id: str,
        request_id: str,
        agent_id: str,
        command: str,
        status: str,
        timestamp: str,
    ) -> None:
        metadata = json.dumps({
            "blocks": [{
                "type": "gh_approval",
                "request_id": request_id,
                "command": command,
                "status": status,
            }],
            "source": "system",
        })
        try:
            db = await get_db()
            await db.execute(
                "INSERT OR IGNORE INTO messages "
                "(id, agent_id, role, content, status, metadata, created_at) "
                "VALUES (?, ?, 'assistant', ?, 'complete', ?, ?)",
                (
                    message_id,
                    agent_id,
                    f"Requesting approval for: gh {command}",
                    metadata,
                    timestamp,
                ),
            )
            await db.commit()
        except Exception:
            logger.exception("Failed to persist approval message %s", message_id)

    async def _update_approval_status(
        self, message_id: str, status: str,
    ) -> None:
        try:
            db = await get_db()
            async with db.execute(
                "SELECT metadata FROM messages WHERE id = ?", (message_id,),
            ) as cur:
                row = await cur.fetchone()
            if not row:
                return
            meta = json.loads(row[0]) if row[0] else {}
            blocks = meta.get("blocks", [])
            for block in blocks:
                if block.get("type") == "gh_approval":
                    block["status"] = status
            meta["blocks"] = blocks
            await db.execute(
                "UPDATE messages SET metadata = ? WHERE id = ?",
                (json.dumps(meta), message_id),
            )
            await db.commit()
        except Exception:
            logger.exception("Failed to update approval status for %s", message_id)
