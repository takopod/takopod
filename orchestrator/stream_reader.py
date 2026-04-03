import asyncio
import json
import logging
import uuid

from fastapi import WebSocket

from orchestrator.db import get_db

logger = logging.getLogger(__name__)


async def _read_stream(
    process: asyncio.subprocess.Process,
    ws: WebSocket,
    session_id: str,
) -> None:
    assert process.stdout is not None

    while True:
        line = await process.stdout.readline()
        if not line:
            break

        line_str = line.decode().strip()
        if not line_str:
            continue

        try:
            event = json.loads(line_str)
        except json.JSONDecodeError:
            continue

        try:
            await ws.send_text(line_str)
        except (ConnectionError, RuntimeError):
            break

        if event.get("type") == "complete":
            db = await get_db()
            await db.execute(
                "INSERT INTO messages (id, session_id, role, content, metadata) "
                "VALUES (?, ?, 'assistant', ?, ?)",
                (
                    str(uuid.uuid4()),
                    session_id,
                    event.get("content", ""),
                    json.dumps(event.get("usage")) if event.get("usage") else None,
                ),
            )
            await db.commit()

    returncode = await process.wait()
    if returncode != 0:
        logger.warning(
            "Worker process exited with code %d for session %s",
            returncode, session_id,
        )


def start_stream_reader(
    process: asyncio.subprocess.Process,
    ws: WebSocket,
    session_id: str,
) -> asyncio.Task:
    return asyncio.create_task(
        _read_stream(process, ws, session_id),
        name=f"stream-{session_id[:8]}",
    )
