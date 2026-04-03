from pathlib import Path

import aiosqlite

DB_PATH = Path("data/rhclaw.db")
MIGRATIONS_DIR = Path(__file__).parent / "migrations"

_db: aiosqlite.Connection | None = None


async def get_db() -> aiosqlite.Connection:
    assert _db is not None, "Database not connected"
    return _db


async def connect() -> aiosqlite.Connection:
    global _db
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    _db = await aiosqlite.connect(DB_PATH)
    await _db.execute("PRAGMA journal_mode=WAL")
    await _db.execute("PRAGMA foreign_keys=ON")
    return _db


async def disconnect() -> None:
    global _db
    if _db is not None:
        await _db.close()
        _db = None


async def get_schema_version(db: aiosqlite.Connection) -> int:
    await db.execute(
        "CREATE TABLE IF NOT EXISTS schema_version ("
        "  version INTEGER NOT NULL,"
        "  applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))"
        ")"
    )
    await db.commit()
    async with db.execute("SELECT MAX(version) FROM schema_version") as cur:
        row = await cur.fetchone()
        return row[0] or 0


async def run_migrations(db: aiosqlite.Connection) -> int:
    current = await get_schema_version(db)
    migration_files = sorted(MIGRATIONS_DIR.glob("*.sql"))

    for mf in migration_files:
        version = int(mf.stem.split("_")[0])
        if version <= current:
            continue
        sql = mf.read_text()
        await db.executescript(sql)
        await db.execute(
            "INSERT INTO schema_version (version) VALUES (?)", (version,)
        )
        await db.commit()
        current = version

    return current
