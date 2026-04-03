"""Thin WebSocket manager: attach, detach, send with asyncio lock."""

import asyncio
import logging

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class WebSocketManager:
    """Manages a single WebSocket connection with serialized sends."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self._ws: WebSocket | None = None
        self._ws_lock = asyncio.Lock()

    def attach(self, ws: WebSocket, session_id: str) -> None:
        self._ws = ws
        self.session_id = session_id

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
                    "WebSocket send failed for session %s, detaching",
                    self.session_id,
                )
                self._ws = None
