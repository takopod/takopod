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
        # Accumulate blocks per message_id for persistence on complete
        self._blocks: dict[str, list[dict]] = {}

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
            name=f"stream-reader-{self.session_id[:8]}",
        )
        self._task.add_done_callback(self._on_task_done)
        return self._task

    def _on_task_done(self, task: asyncio.Task) -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc:
            logger.error(
                "Stream reader task crashed for session %s: %s",
                self.session_id, exc,
            )

    def cancel(self) -> None:
        if self._task:
            self._task.cancel()

    def restart_if_dead(self) -> None:
        """Restart the tail loop if the task has exited unexpectedly."""
        if self._task is not None and not self._task.done():
            return
        if self._task and self._task.done() and not self._task.cancelled():
            exc = self._task.exception()
            if exc:
                logger.error(
                    "Stream reader was dead (crashed: %s), restarting",
                    exc,
                )
            else:
                logger.warning("Stream reader was dead (exited cleanly), restarting")
        else:
            logger.info("Stream reader not started, starting")
        self.start()

    async def _process_event(self, line: str) -> None:
        """Parse, forward, and persist a single JSONL event."""
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            return

        await self.send(line)

        event_type = event.get("type")
        message_id = event.get("message_id", "")

        if event_type == "token":
            blocks = self._blocks.setdefault(message_id, [])
            if blocks and blocks[-1]["type"] == "text":
                blocks[-1]["text"] += event.get("content", "")
            else:
                blocks.append({"type": "text", "text": event.get("content", "")})

        elif event_type == "tool_call":
            logger.info(
                "Tool call: %s (id=%s) for session %s",
                event.get("tool_name"), event.get("tool_call_id"),
                self.session_id,
            )
            self._blocks.setdefault(message_id, []).append({
                "type": "tool_call",
                "tool": {
                    "tool_name": event.get("tool_name", "unknown"),
                    "tool_input": event.get("tool_input", {}),
                    "tool_call_id": event.get("tool_call_id", ""),
                },
            })

        elif event_type == "tool_result":
            logger.info(
                "Tool result: id=%s for session %s",
                event.get("tool_call_id"), self.session_id,
            )
            tc_id = event.get("tool_call_id")
            for block in self._blocks.get(message_id, []):
                if block["type"] == "tool_call" and block["tool"].get("tool_call_id") == tc_id:
                    block["tool"]["output"] = event.get("output", "")
                    break

        elif event_type == "system_error":
            logger.warning(
                "Worker error for session %s: %s",
                self.session_id, event.get("error"),
            )

        if event_type == "complete":
            blocks = self._blocks.pop(message_id, None)
            metadata = {}
            if event.get("usage"):
                metadata["usage"] = event["usage"]
            if blocks:
                metadata["blocks"] = blocks
            try:
                db = await get_db()
                await db.execute(
                    "INSERT INTO messages (id, session_id, role, content, metadata) "
                    "VALUES (?, ?, 'assistant', ?, ?)",
                    (
                        str(uuid.uuid4()),
                        self.session_id,
                        event.get("content", ""),
                        json.dumps(metadata) if metadata else None,
                    ),
                )
                await db.commit()
            except Exception:
                logger.exception(
                    "Failed to persist complete event for session %s",
                    self.session_id,
                )

    _POLL_MIN = 0.5   # 500ms when active
    _POLL_MAX = 5.0   # 5s when idle

    async def _tail_loop(self) -> None:
        """Tail the output JSONL file, forwarding events as they appear.

        Uses a close-and-reopen pattern instead of a long-lived file handle.
        On macOS with podman bind mounts (virtiofs), a persistent handle
        caches file metadata and misses data written by the container after
        the host-side handle hits EOF.  Reopening on each poll gives us
        close-to-open consistency.

        Polls with exponential backoff: 500ms while active, doubling up to
        5s when idle, resetting to 500ms when new data arrives.
        """
        while not self.output_path.exists():
            await asyncio.sleep(0.5)

        pos = self.output_path.stat().st_size  # start from current end
        delay = self._POLL_MIN

        while True:
            try:
                try:
                    size = self.output_path.stat().st_size
                except OSError:
                    await asyncio.sleep(delay)
                    continue

                if size < pos:
                    # File was truncated (new container started)
                    pos = 0

                if size <= pos:
                    delay = min(delay * 2, self._POLL_MAX)
                    await asyncio.sleep(delay)
                    continue

                # New data available — reset to fast polling
                delay = self._POLL_MIN

                try:
                    with open(self.output_path, "rb") as fh:
                        fh.seek(pos)
                        data = fh.read()
                except OSError:
                    await asyncio.sleep(delay)
                    continue

                if not data:
                    await asyncio.sleep(delay)
                    continue

                # Only process up to the last complete line (ends with \n).
                # Partial lines at the end are left for the next iteration.
                last_nl = data.rfind(b"\n")
                if last_nl == -1:
                    await asyncio.sleep(delay)
                    continue

                complete_chunk = data[: last_nl + 1]
                pos += len(complete_chunk)

                for raw_line in complete_chunk.split(b"\n"):
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line:
                        continue
                    try:
                        await self._process_event(line)
                    except Exception:
                        logger.exception(
                            "Unhandled error processing event for session %s",
                            self.session_id,
                        )

            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "Unexpected error in tail loop for session %s",
                    self.session_id,
                )
                await asyncio.sleep(self._POLL_MIN)
