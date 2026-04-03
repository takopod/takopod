import asyncio
import json
import logging
import time
from pathlib import Path

from fastapi import WebSocket

from orchestrator.db import get_db

logger = logging.getLogger(__name__)

# Minimum interval between WebSocket notifications for the same message
_NOTIFY_INTERVAL = 0.3  # 300ms


class StreamReader:
    """Tails /workspace/output.jsonl from a worker container.

    Reads the JSONL output file on the bind-mounted host directory,
    bypassing podman's stdout relay to avoid buffering issues.

    Every event is persisted to the DB immediately. The WebSocket receives
    throttled ``message_updated`` notifications so the frontend can fetch
    the latest state from the API.
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
        # Throttle state per message_id
        self._last_notify: dict[str, float] = {}
        self._pending_notify: dict[str, asyncio.TimerHandle] = {}

    def attach(self, ws: WebSocket, session_id: str) -> None:
        self._ws = ws
        self.session_id = session_id

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
        # Cancel any pending deferred notifications
        for handle in self._pending_notify.values():
            handle.cancel()
        self._pending_notify.clear()

    def restart_if_dead(self) -> None:
        if self._task is not None and not self._task.done():
            return
        if self._task and self._task.done() and not self._task.cancelled():
            exc = self._task.exception()
            if exc:
                logger.error(
                    "Stream reader was dead (crashed: %s), restarting", exc,
                )
            else:
                logger.warning("Stream reader was dead (exited cleanly), restarting")
        else:
            logger.info("Stream reader not started, starting")
        self.start()

    # --- Notification throttling ---

    async def _notify(self, row_id: str) -> None:
        frame = json.dumps({"type": "message_updated", "message_id": row_id})
        await self.send(frame)

    def _schedule_notify(self, row_id: str, immediate: bool = False) -> None:
        now = time.monotonic()
        last = self._last_notify.get(row_id, 0.0)
        elapsed = now - last

        # Cancel any existing deferred notification for this message
        pending = self._pending_notify.pop(row_id, None)
        if pending:
            pending.cancel()

        if immediate or elapsed >= _NOTIFY_INTERVAL:
            self._last_notify[row_id] = now
            asyncio.ensure_future(self._notify(row_id))
        else:
            # Defer notification to ensure frontend gets the latest state
            delay = _NOTIFY_INTERVAL - elapsed
            loop = asyncio.get_running_loop()
            handle = loop.call_later(
                delay,
                lambda rid=row_id: asyncio.ensure_future(self._flush_notify(rid)),
            )
            self._pending_notify[row_id] = handle

    async def _flush_notify(self, row_id: str) -> None:
        self._pending_notify.pop(row_id, None)
        self._last_notify[row_id] = time.monotonic()
        await self._notify(row_id)

    # --- DB persistence ---

    async def _process_event(self, line: str) -> None:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            return

        event_type = event.get("type")

        # Forward context_cleared directly — it has no message_id
        if event_type == "status" and event.get("status") == "context_cleared":
            await self.send(line)
            return

        message_id = event.get("message_id", "")
        if not message_id:
            return

        row_id = f"assistant-{message_id}"

        if event_type == "status" and event.get("status") == "thinking":
            await self._db_ensure_row(row_id)
            self._schedule_notify(row_id)

        elif event_type == "token":
            await self._db_ensure_row(row_id)
            content = event.get("content", "")
            await self._db_append_token(row_id, content)
            self._schedule_notify(row_id)

        elif event_type == "tool_call":
            await self._db_ensure_row(row_id)
            block = {
                "type": "tool_call",
                "tool": {
                    "tool_name": event.get("tool_name", "unknown"),
                    "tool_input": event.get("tool_input", {}),
                    "tool_call_id": event.get("tool_call_id", ""),
                },
            }
            await self._db_append_block(row_id, block)
            self._schedule_notify(row_id)

        elif event_type == "tool_result":
            tc_id = event.get("tool_call_id", "")
            output = event.get("output", "")
            await self._db_update_tool_result(row_id, tc_id, output)
            self._schedule_notify(row_id)

        elif event_type == "complete":
            usage = event.get("usage")
            content = event.get("content", "")
            await self._db_complete(row_id, content, usage)
            # Always notify immediately on complete
            self._schedule_notify(row_id, immediate=True)

    async def _db_ensure_row(self, row_id: str) -> None:
        metadata = json.dumps({"blocks": []})
        try:
            db = await get_db()
            await db.execute(
                "INSERT OR IGNORE INTO messages "
                "(id, session_id, role, content, status, metadata) "
                "VALUES (?, ?, 'assistant', '', 'streaming', ?)",
                (row_id, self.session_id, metadata),
            )
            await db.commit()
        except Exception:
            logger.exception("Failed to insert message %s", row_id)

    async def _db_append_token(self, row_id: str, content: str) -> None:
        try:
            db = await get_db()
            row = await self._db_get_metadata(db, row_id)
            if row is None:
                return
            current_content, meta = row

            blocks = meta.get("blocks", [])
            if blocks and blocks[-1]["type"] == "text":
                blocks[-1]["text"] += content
            else:
                blocks.append({"type": "text", "text": content})
            meta["blocks"] = blocks

            await db.execute(
                "UPDATE messages SET content = ?, metadata = ? WHERE id = ?",
                (current_content + content, json.dumps(meta), row_id),
            )
            await db.commit()
        except Exception:
            logger.exception("Failed to append token to %s", row_id)

    async def _db_append_block(self, row_id: str, block: dict) -> None:
        try:
            db = await get_db()
            row = await self._db_get_metadata(db, row_id)
            if row is None:
                return
            _, meta = row

            meta.setdefault("blocks", []).append(block)

            await db.execute(
                "UPDATE messages SET metadata = ? WHERE id = ?",
                (json.dumps(meta), row_id),
            )
            await db.commit()
        except Exception:
            logger.exception("Failed to append block to %s", row_id)

    async def _db_update_tool_result(
        self, row_id: str, tool_call_id: str, output: str,
    ) -> None:
        try:
            db = await get_db()
            row = await self._db_get_metadata(db, row_id)
            if row is None:
                return
            _, meta = row

            for block in meta.get("blocks", []):
                if (
                    block["type"] == "tool_call"
                    and block["tool"].get("tool_call_id") == tool_call_id
                ):
                    block["tool"]["output"] = output
                    break

            await db.execute(
                "UPDATE messages SET metadata = ? WHERE id = ?",
                (json.dumps(meta), row_id),
            )
            await db.commit()
        except Exception:
            logger.exception("Failed to update tool result in %s", row_id)

    async def _db_complete(
        self, row_id: str, content: str, usage: dict | None,
    ) -> None:
        try:
            db = await get_db()
            row = await self._db_get_metadata(db, row_id)
            if row is None:
                return
            _, meta = row

            if usage:
                meta["usage"] = usage

            await db.execute(
                "UPDATE messages SET content = ?, status = 'complete', metadata = ? "
                "WHERE id = ?",
                (content, json.dumps(meta), row_id),
            )
            await db.commit()
        except Exception:
            logger.exception("Failed to complete message %s", row_id)

    @staticmethod
    async def _db_get_metadata(db, row_id: str) -> tuple[str, dict] | None:
        async with db.execute(
            "SELECT content, metadata FROM messages WHERE id = ?", (row_id,),
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            logger.warning("Message %s not found for update", row_id)
            return None
        content = row[0] or ""
        try:
            meta = json.loads(row[1]) if row[1] else {}
        except json.JSONDecodeError:
            meta = {}
        return content, meta

    # --- File tailing ---

    _POLL_MIN = 0.5
    _POLL_MAX = 5.0

    async def _tail_loop(self) -> None:
        while not self.output_path.exists():
            await asyncio.sleep(0.5)

        pos = 0
        delay = self._POLL_MIN

        while True:
            try:
                try:
                    size = self.output_path.stat().st_size
                except OSError:
                    await asyncio.sleep(delay)
                    continue

                if size < pos:
                    pos = 0

                if size <= pos:
                    delay = min(delay * 2, self._POLL_MAX)
                    await asyncio.sleep(delay)
                    continue

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
