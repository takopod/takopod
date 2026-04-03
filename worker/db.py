"""Worker database: synchronous SQLite with WAL mode and numbered migrations."""

import sqlite3
from pathlib import Path

DB_PATH = Path("/workspace/worker_db.sqlite")
MIGRATIONS_DIR = Path(__file__).parent / "migrations"

_db: sqlite3.Connection | None = None


def get_db() -> sqlite3.Connection:
    assert _db is not None, "Database not connected"
    return _db


def connect() -> sqlite3.Connection:
    global _db
    _db = sqlite3.connect(str(DB_PATH))
    _db.execute("PRAGMA journal_mode=WAL")
    _db.execute("PRAGMA foreign_keys=ON")

    import sqlite_vec
    _db.enable_load_extension(True)
    sqlite_vec.load(_db)
    _db.enable_load_extension(False)

    return _db


def disconnect() -> None:
    global _db
    if _db is not None:
        _db.close()
        _db = None


def _get_schema_version(db: sqlite3.Connection) -> int:
    db.execute(
        "CREATE TABLE IF NOT EXISTS schema_version ("
        "  version INTEGER NOT NULL,"
        "  applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))"
        ")"
    )
    db.commit()
    row = db.execute("SELECT MAX(version) FROM schema_version").fetchone()
    return row[0] or 0


def run_migrations(db: sqlite3.Connection) -> int:
    current = _get_schema_version(db)
    migration_files = sorted(MIGRATIONS_DIR.glob("*.sql"))

    for mf in migration_files:
        version = int(mf.stem.split("_")[0])
        if version <= current:
            continue
        sql = mf.read_text()
        db.executescript(sql)
        db.execute(
            "INSERT INTO schema_version (version) VALUES (?)", (version,)
        )
        db.commit()
        current = version

    return current
