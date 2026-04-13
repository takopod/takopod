"""Thin WebSocket manager: attach, detach, send with asyncio lock."""

import asyncio
import logging

from fastapi import WebSocket

logger = logging.getLogger(__name__)

# Application-specific WebSocket close codes (4000-4999 range)
WS_CLOSE_IDLE_TIMEOUT = 4001
WS_CLOSE_ADMIN_KILL = 4002


class WebSocketManager:
    """Manages a single WebSocket connection with serialized sends."""

    def __init__(self, agent_id: str):
        self.agent_id = agent_id
        self._ws: WebSocket | None = None
        self._ws_lock = asyncio.Lock()

    def attach(self, ws: WebSocket) -> None:
        self._ws = ws

    @property
    def connected(self) -> bool:
        return self._ws is not None

    def detach(self) -> None:
        self._ws = None

    async def send(self, text: str) -> None:
        async with self._ws_lock:
            ws = self._ws
            if ws is None:
                return
            try:
                await ws.send_text(text)
            except (ConnectionError, RuntimeError):
                logger.warning(
                    "WebSocket send failed for agent %s, detaching",
                    self.agent_id,
                )
                self._ws = None

    async def close(self, code: int, reason: str = "") -> None:
        """Send a close frame with an application-specific code and detach."""
        async with self._ws_lock:
            ws = self._ws
            if ws is None:
                return
            try:
                await ws.close(code=code, reason=reason)
            except (ConnectionError, RuntimeError):
                logger.warning(
                    "WebSocket close failed for agent %s (client already gone)",
                    self.agent_id,
                )
            self._ws = None
