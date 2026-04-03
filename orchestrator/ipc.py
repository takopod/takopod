import json

from orchestrator.db import get_db


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
