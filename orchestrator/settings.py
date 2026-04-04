"""Settings: key-value store backed by SQLite."""

from orchestrator.db import get_db


async def get_setting(key: str, default: str | None = None) -> str | None:
    db = await get_db()
    async with db.execute(
        "SELECT value FROM settings WHERE key = ?", (key,)
    ) as cur:
        row = await cur.fetchone()
    return row[0] if row else default


async def set_setting(key: str, value: str) -> None:
    db = await get_db()
    await db.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    await db.commit()


async def get_all_settings() -> dict[str, str]:
    db = await get_db()
    async with db.execute("SELECT key, value FROM settings") as cur:
        rows = await cur.fetchall()
    return {r[0]: r[1] for r in rows}
