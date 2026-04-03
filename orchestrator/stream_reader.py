import asyncio
import json
import logging
import uuid
from pathlib import Path

from fastapi import WebSocket

from orchestrator.db import get_db

logger = logging.getLogger(__name__)


class StreamReader:
    """Tails /workspace/output.jsonl from a worker container.

    Reads the JSONL output file on the bind-mounted host directory,
    bypassing podman's stdout relay to avoid buffering issues.

    The WebSocket can be attached/detached as clients connect/disconnect.
    The reader keeps running regardless — events without a WebSocket are
    still persisted to the DB but not forwarded to a client.
    """

    def __init__(
        self,
        output_path: Path,
        session_id: str,
    ) -> None:
        self.output_path = output_path
        self.session_id = session_id
        self._ws: WebSocket | None = None
        self._ws_lock = asyncio.Lock()
        self._task: asyncio.Task | None = None

    def attach(self, ws: WebSocket, session_id: str) -> None:
        """Attach a WebSocket to receive forwarded events."""
        self._ws = ws
        self.session_id = session_id

    def detach(self) -> None:
        """Detach the WebSocket. Events are still read and persisted."""
        self._ws = None

    async def send(self, text: str) -> None:
        """Send text on the attached WebSocket, serialized by a lock."""
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

    def start(self) -> asyncio.Task:
        self._task = asyncio.create_task(
            self._tail_loop(),
            name="stream-reader",
        )
        return self._task

    def cancel(self) -> None:
        if self._task:
            self._task.cancel()

    async def _tail_loop(self) -> None:
        """Tail the output JSONL file, forwarding events as they appear."""
        # Wait for the file to exist (container is starting up)
        while not self.output_path.exists():
            await asyncio.sleep(0.2)

        with open(self.output_path) as fh:
            # Seek to end — we only care about new events
            fh.seek(0, 2)

            while True:
                line = fh.readline()
                if not line:
                    await asyncio.sleep(0.05)
                    continue

                line = line.strip()
                if not line:
                    continue

                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue

                # Forward to WebSocket
                await self.send(line)

                event_type = event.get("type")

                if event_type == "tool_call":
                    logger.info(
                        "Tool call: %s (id=%s) for session %s",
                        event.get("tool_name"), event.get("tool_call_id"),
                        self.session_id,
                    )
                elif event_type == "tool_result":
                    logger.info(
                        "Tool result: id=%s for session %s",
                        event.get("tool_call_id"), self.session_id,
                    )
                elif event_type == "system_error":
                    logger.warning(
                        "Worker error for session %s: %s",
                        self.session_id, event.get("error"),
                    )

                if event_type == "complete":
                    db = await get_db()
                    await db.execute(
                        "INSERT INTO messages (id, session_id, role, content, metadata) "
                        "VALUES (?, ?, 'assistant', ?, ?)",
                        (
                            str(uuid.uuid4()),
                            self.session_id,
                            event.get("content", ""),
                            json.dumps(event.get("usage")) if event.get("usage") else None,
                        ),
                    )
                    await db.commit()
