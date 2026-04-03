import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import WebSocket

from orchestrator.db import get_db
from orchestrator.models import QueueStatusFrame

logger = logging.getLogger(__name__)


async def queue_message(session_id: str, message_id: str, content: str) -> None:
    db = await get_db()
    payload = json.dumps({
        "message_id": message_id,
        "type": "user_message",
        "content": content,
    })
    await db.execute(
        "INSERT INTO message_queue (id, session_id, payload) VALUES (?, ?, ?)",
        (message_id, session_id, payload),
    )
    await db.commit()


async def get_queue_counts(session_id: str) -> dict[str, int]:
    db = await get_db()
    counts = {"queued": 0, "in_flight": 0, "processed": 0}
    async with db.execute(
        "SELECT status, COUNT(*) FROM message_queue WHERE session_id = ? GROUP BY status",
        (session_id,),
    ) as cur:
        async for row in cur:
            key = row[0].lower().replace("-", "_")
            counts[key] = row[1]
    return counts


def atomic_write(path: Path, data: bytes) -> None:
    temp_path = path.parent / f"{path.name}.tmp.{os.getpid()}"
    try:
        fd = os.open(str(temp_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
        try:
            os.write(fd, data)
            os.fsync(fd)
        finally:
            os.close(fd)
        os.rename(str(temp_path), str(path))
    except BaseException:
        try:
            os.unlink(str(temp_path))
        except FileNotFoundError:
            pass
        raise


async def _send_queue_status(ws: WebSocket, session_id: str) -> None:
    counts = await get_queue_counts(session_id)
    frame = QueueStatusFrame(**counts)
    await ws.send_text(frame.model_dump_json())


async def _polling_loop(
    session_id: str, host_dir: Path, ws: WebSocket
) -> None:
    input_path = host_dir / "input.json"
    db = await get_db()

    while True:
        await asyncio.sleep(0.5)
        try:
            # ACK check: IN-FLIGHT messages + input.json gone = PROCESSED
            async with db.execute(
                "SELECT COUNT(*) FROM message_queue "
                "WHERE session_id = ? AND status = 'IN-FLIGHT'",
                (session_id,),
            ) as cur:
                row = await cur.fetchone()
                in_flight_count = row[0]

            if in_flight_count > 0 and not input_path.exists():
                now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                await db.execute(
                    "UPDATE message_queue SET status = 'PROCESSED', processed_at = ? "
                    "WHERE session_id = ? AND status = 'IN-FLIGHT'",
                    (now, session_id),
                )
                await db.commit()
                await _send_queue_status(ws, session_id)

            # Flush check: QUEUED messages + no input.json = write input.json
            async with db.execute(
                "SELECT id, payload FROM message_queue "
                "WHERE session_id = ? AND status = 'QUEUED' "
                "ORDER BY created_at",
                (session_id,),
            ) as cur:
                queued = await cur.fetchall()

            if queued and not input_path.exists():
                messages = [json.loads(row[1]) for row in queued]
                now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                for msg in messages:
                    msg["timestamp"] = now

                atomic_write(input_path, json.dumps(messages).encode())

                ids = [row[0] for row in queued]
                placeholders = ",".join("?" * len(ids))
                await db.execute(
                    f"UPDATE message_queue SET status = 'IN-FLIGHT', flushed_at = ? "
                    f"WHERE id IN ({placeholders})",
                    (now, *ids),
                )
                await db.commit()
                await _send_queue_status(ws, session_id)

        except (ConnectionError, RuntimeError):
            # WebSocket disconnected
            break
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Polling loop error for session %s", session_id)


def start_polling_loop(
    session_id: str, host_dir: Path, ws: WebSocket
) -> asyncio.Task:
    return asyncio.create_task(
        _polling_loop(session_id, host_dir, ws),
        name=f"poll-{session_id[:8]}",
    )
