import asyncio
import json
import logging
import uuid

from fastapi import WebSocket

from orchestrator.db import get_db

logger = logging.getLogger(__name__)


class StreamReader:
    """Reads JSONL from a worker process's stdout for its entire lifetime.

    The WebSocket can be attached/detached as clients connect/disconnect.
    The reader keeps running regardless — events without a WebSocket are
    still persisted to the DB but not forwarded to a client.
    """

    def __init__(
        self,
        process: asyncio.subprocess.Process,
        session_id: str,
    ) -> None:
        self.process = process
        self.session_id = session_id
        self._ws: WebSocket | None = None
        self._task: asyncio.Task | None = None

    def attach(self, ws: WebSocket, session_id: str) -> None:
        """Attach a WebSocket to receive forwarded events."""
        self._ws = ws
        self.session_id = session_id

    def detach(self) -> None:
        """Detach the WebSocket. Events are still read and persisted."""
        self._ws = None

    def start(self) -> asyncio.Task:
        self._task = asyncio.create_task(
            self._read_loop(),
            name=f"stream-reader",
        )
        return self._task

    def cancel(self) -> None:
        if self._task:
            self._task.cancel()

    async def _read_loop(self) -> None:
        assert self.process.stdout is not None

        while True:
            line = await self.process.stdout.readline()
            if not line:
                break

            line_str = line.decode().strip()
            if not line_str:
                continue

            try:
                event = json.loads(line_str)
            except json.JSONDecodeError:
                continue

            # Forward to WebSocket if one is attached
            if self._ws is not None:
                try:
                    await self._ws.send_text(line_str)
                except (ConnectionError, RuntimeError):
                    self._ws = None

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

        returncode = await self.process.wait()
        if returncode != 0:
            logger.warning(
                "Worker process exited with code %d for session %s",
                returncode, self.session_id,
            )
