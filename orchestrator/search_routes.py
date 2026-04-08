"""Search index management API routes.

Provides endpoints to inspect, edit, delete, and rebuild the per-agent
FTS5 and vec0 search indexes stored in worker databases.  Also exposes
memory file management for viewing and deleting agent memory files.

The orchestrator opens worker databases directly (synchronous sqlite3
via run_in_executor) — this is the only place where the orchestrator
reaches into worker DB files.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
import urllib.error
import urllib.request
import asyncio
from pathlib import Path

from fastapi import APIRouter, HTTPException

from orchestrator.db import get_db
from orchestrator.models import (
    SearchIndexEntry,
    SearchIndexStats,
    SearchIndexUpdateRequest,
    ReindexRequest,
    ReindexResponse,
    MemoryFileEntry,
)

logger = logging.getLogger(__name__)

router = APIRouter()

DATA_DIR = Path("data")
OLLAMA_URL = os.environ.get("OLLAMA_HOST_URL", "http://localhost:11434")
EMBED_MODEL = "nomic-embed-text"

SEARCH_TABLES_SQL = """\
CREATE VIRTUAL TABLE IF NOT EXISTS message_fts USING fts5(
    content,
    role,
    session_id UNINDEXED,
    message_id UNINDEXED,
    created_at UNINDEXED,
    tokenize = 'porter'
);

CREATE VIRTUAL TABLE IF NOT EXISTS message_vec USING vec0(
    embedding float[768],
    +content TEXT,
    +role TEXT,
    +session_id TEXT,
    +message_id TEXT,
    +created_at TEXT
);
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _open_worker_db(agent_id: str) -> sqlite3.Connection:
    """Open a synchronous connection to an agent's worker database.

    Raises FileNotFoundError if the worker DB doesn't exist (agent never started).
    Callers running inside run_in_executor should let this propagate —
    the _handle_worker_db_error wrapper will convert it to an HTTPException.
    """
    path = DATA_DIR / "agents" / agent_id / "worker_db.sqlite"
    if not path.is_file():
        raise FileNotFoundError(f"Worker DB not found: {path}")
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        import sqlite_vec
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
    except ImportError:
        pass
    return conn


async def _validate_agent(agent_id: str) -> None:
    """Raise 404 if agent doesn't exist."""
    db = await get_db()
    async with db.execute(
        "SELECT id FROM agents WHERE id = ? AND status = 'active'",
        (agent_id,),
    ) as cur:
        if not await cur.fetchone():
            raise HTTPException(status_code=404, detail="Agent not found")


async def _run_worker_op(func):
    """Run a synchronous worker DB operation in an executor, converting FileNotFoundError."""
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(None, func)
    except FileNotFoundError:
        raise HTTPException(
            status_code=404,
            detail="Worker database not found. Start the agent at least once to create it.",
        )


def _sanitize_fts5_query(text: str) -> str:
    """Escape special FTS5 characters by quoting each word."""
    import re
    words = re.findall(r"\w+", text)
    if not words:
        return '""'
    return " OR ".join(f'"{w}"' for w in words)


def _embed_sync(text: str) -> list[float] | None:
    """Synchronous embedding call to host-side Ollama. Returns None on failure."""
    url = f"{OLLAMA_URL}/api/embed"
    payload = json.dumps({"model": EMBED_MODEL, "input": text}).encode()
    req = urllib.request.Request(
        url, data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        return data["embeddings"][0]
    except (urllib.error.URLError, OSError, KeyError) as e:
        logger.warning("Ollama embed failed: %s", e)
        return None


def _check_ollama() -> bool:
    """Quick connectivity check for Ollama."""
    try:
        urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=5)
        return True
    except (urllib.error.URLError, OSError):
        return False


# ---------------------------------------------------------------------------
# Search / List
# ---------------------------------------------------------------------------


@router.get("/agents/{agent_id}/search-index")
async def search_index(agent_id: str, q: str = "", limit: int = 50):
    """Search or list entries in the agent's FTS index."""
    await _validate_agent(agent_id)

    def _query():
        conn = _open_worker_db(agent_id)
        try:
            if q.strip():
                fts_query = _sanitize_fts5_query(q)
                rows = conn.execute(
                    "SELECT message_id, content, role, session_id, created_at, rank "
                    "FROM message_fts WHERE message_fts MATCH ? "
                    "ORDER BY rank LIMIT ?",
                    (fts_query, min(limit, 200)),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT message_id, content, role, session_id, created_at, 0.0 "
                    "FROM message_fts ORDER BY rowid DESC LIMIT ?",
                    (min(limit, 200),),
                ).fetchall()
            return [
                {
                    "message_id": r[0], "content": r[1], "role": r[2],
                    "session_id": r[3], "created_at": r[4], "rank": r[5],
                }
                for r in rows
            ]
        finally:
            conn.close()

    return await _run_worker_op(_query)


# ---------------------------------------------------------------------------
# Stats (must be before {message_id} to avoid path parameter capture)
# ---------------------------------------------------------------------------


@router.get("/agents/{agent_id}/search-index/stats")
async def index_stats(agent_id: str):
    """Return index health stats: counts and sync status."""
    await _validate_agent(agent_id)

    orch_db = await get_db()
    async with orch_db.execute(
        "SELECT COUNT(*) FROM messages m "
        "JOIN sessions s ON s.id = m.session_id "
        "WHERE s.agent_id = ? AND m.visibility = 'visible'",
        (agent_id,),
    ) as cur:
        orch_count = (await cur.fetchone())[0]

    def _worker_stats():
        conn = _open_worker_db(agent_id)
        try:
            fts_count = conn.execute("SELECT COUNT(*) FROM message_fts").fetchone()[0]
            try:
                vec_count = conn.execute("SELECT COUNT(*) FROM message_vec").fetchone()[0]
            except sqlite3.OperationalError:
                vec_count = 0
            return {"fts_count": fts_count, "vec_count": vec_count}
        finally:
            conn.close()

    worker = await _run_worker_op(_worker_stats)
    return {
        "orchestrator_count": orch_count,
        "fts_count": worker["fts_count"],
        "vec_count": worker["vec_count"],
    }


# ---------------------------------------------------------------------------
# Reindex (must be before {message_id} to avoid path parameter capture)
# ---------------------------------------------------------------------------


@router.post("/agents/{agent_id}/search-index/reindex")
async def reindex(agent_id: str, req: ReindexRequest | None = None):
    """Reindex specific entries or perform a full rebuild from orchestrator source of truth."""
    await _validate_agent(agent_id)

    orch_db = await get_db()

    if req and req.message_ids:
        return await _reindex_messages(agent_id, req.message_ids, orch_db)

    return await _full_rebuild(agent_id, orch_db)


# ---------------------------------------------------------------------------
# Single entry detail
# ---------------------------------------------------------------------------


@router.get("/agents/{agent_id}/search-index/{message_id}")
async def get_index_entry(agent_id: str, message_id: str):
    """Get full details of a single indexed entry."""
    await _validate_agent(agent_id)

    def _query():
        conn = _open_worker_db(agent_id)
        try:
            row = conn.execute(
                "SELECT message_id, content, role, session_id, created_at "
                "FROM message_fts WHERE message_id = ? LIMIT 1",
                (message_id,),
            ).fetchone()
            if not row:
                return None

            vec_row = conn.execute(
                "SELECT rowid FROM message_vec WHERE message_id = ? LIMIT 1",
                (message_id,),
            ).fetchone()
            return {
                "message_id": row[0], "content": row[1], "role": row[2],
                "session_id": row[3], "created_at": row[4],
                "has_embedding": vec_row is not None,
            }
        finally:
            conn.close()

    result = await _run_worker_op(_query)
    if not result:
        raise HTTPException(status_code=404, detail="Entry not found in index")
    return result


# ---------------------------------------------------------------------------
# Update entry
# ---------------------------------------------------------------------------


@router.put("/agents/{agent_id}/search-index/{message_id}")
async def update_index_entry(
    agent_id: str, message_id: str, req: SearchIndexUpdateRequest,
):
    """Update content in worker FTS and vec indexes (not the orchestrator source of truth)."""
    await _validate_agent(agent_id)

    def _update():
        conn = _open_worker_db(agent_id)
        try:
            # Get existing row metadata
            row = conn.execute(
                "SELECT role, session_id, created_at FROM message_fts "
                "WHERE message_id = ? LIMIT 1",
                (message_id,),
            ).fetchone()
            if not row:
                return {"error": "not_found"}

            role, session_id, created_at = row

            # Delete old FTS entry and insert new
            conn.execute(
                "DELETE FROM message_fts WHERE rowid IN ("
                "  SELECT rowid FROM message_fts WHERE message_id = ?"
                ")",
                (message_id,),
            )
            conn.execute(
                "INSERT INTO message_fts (content, role, session_id, message_id, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (req.content, role, session_id, message_id, created_at),
            )

            # Delete old vec entry and re-embed
            vec_warning = None
            conn.execute(
                "DELETE FROM message_vec WHERE rowid IN ("
                "  SELECT rowid FROM message_vec WHERE message_id = ?"
                ")",
                (message_id,),
            )
            embedding = _embed_sync(req.content)
            if embedding:
                conn.execute(
                    "INSERT INTO message_vec (embedding, content, role, session_id, message_id, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (json.dumps(embedding), req.content, role, session_id, message_id, created_at),
                )
            else:
                vec_warning = "Ollama unreachable — FTS updated but vector embedding skipped"

            conn.commit()
            return {"updated": True, "warning": vec_warning}
        finally:
            conn.close()

    result = await _run_worker_op(_update)
    if result.get("error") == "not_found":
        raise HTTPException(status_code=404, detail="Entry not found in index")
    return result


# ---------------------------------------------------------------------------
# Delete entry
# ---------------------------------------------------------------------------


@router.delete("/agents/{agent_id}/search-index/{message_id}")
async def delete_index_entry(agent_id: str, message_id: str):
    """Delete an entry from worker FTS and vec indexes."""
    await _validate_agent(agent_id)

    def _delete():
        conn = _open_worker_db(agent_id)
        try:
            fts_deleted = conn.execute(
                "DELETE FROM message_fts WHERE rowid IN ("
                "  SELECT rowid FROM message_fts WHERE message_id = ?"
                ")",
                (message_id,),
            ).rowcount
            vec_deleted = conn.execute(
                "DELETE FROM message_vec WHERE rowid IN ("
                "  SELECT rowid FROM message_vec WHERE message_id = ?"
                ")",
                (message_id,),
            ).rowcount
            conn.commit()
            return {"fts_deleted": fts_deleted, "vec_deleted": vec_deleted}
        finally:
            conn.close()

    return await _run_worker_op(_delete)


async def _reindex_messages(agent_id: str, message_ids: list[str], orch_db):
    """Reindex specific messages from orchestrator source of truth."""
    # Fetch messages from orchestrator
    placeholders = ",".join("?" for _ in message_ids)
    async with orch_db.execute(
        f"SELECT m.id, m.session_id, m.role, m.content, m.created_at "
        f"FROM messages m "
        f"JOIN sessions s ON s.id = m.session_id "
        f"WHERE s.agent_id = ? AND m.id IN ({placeholders})",
        [agent_id, *message_ids],
    ) as cur:
        messages = await cur.fetchall()

    def _do_reindex():
        conn = _open_worker_db(agent_id)
        indexed = 0
        errors = 0
        skipped_vectors = False
        try:
            for msg_id, session_id, role, content, created_at in messages:
                try:
                    # Delete old entries
                    conn.execute(
                        "DELETE FROM message_fts WHERE rowid IN ("
                        "  SELECT rowid FROM message_fts WHERE message_id = ?"
                        ")", (msg_id,),
                    )
                    conn.execute(
                        "DELETE FROM message_vec WHERE rowid IN ("
                        "  SELECT rowid FROM message_vec WHERE message_id = ?"
                        ")", (msg_id,),
                    )
                    # Re-insert FTS
                    conn.execute(
                        "INSERT INTO message_fts (content, role, session_id, message_id, created_at) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (content, role, session_id, msg_id, created_at),
                    )
                    # Re-insert vec
                    embedding = _embed_sync(content)
                    if embedding:
                        conn.execute(
                            "INSERT INTO message_vec (embedding, content, role, session_id, message_id, created_at) "
                            "VALUES (?, ?, ?, ?, ?, ?)",
                            (json.dumps(embedding), content, role, session_id, msg_id, created_at),
                        )
                    else:
                        skipped_vectors = True
                    indexed += 1
                except Exception as e:
                    logger.warning("Reindex failed for %s: %s", msg_id, e)
                    errors += 1
            conn.commit()
            return {"indexed": indexed, "errors": errors, "skipped_vectors": skipped_vectors}
        finally:
            conn.close()

    return await _run_worker_op(_do_reindex)


async def _full_rebuild(agent_id: str, orch_db):
    """Drop and recreate indexes, re-index all messages from orchestrator."""
    # Fetch all messages for this agent
    async with orch_db.execute(
        "SELECT m.id, m.session_id, m.role, m.content, m.created_at "
        "FROM messages m "
        "JOIN sessions s ON s.id = m.session_id "
        "WHERE s.agent_id = ? AND m.visibility = 'visible' "
        "ORDER BY m.created_at",
        (agent_id,),
    ) as cur:
        messages = await cur.fetchall()

    def _do_rebuild():
        conn = _open_worker_db(agent_id)
        indexed = 0
        errors = 0
        skipped_vectors = False
        try:
            # Drop and recreate tables
            conn.execute("DROP TABLE IF EXISTS message_fts")
            conn.execute("DROP TABLE IF EXISTS message_vec")
            conn.executescript(SEARCH_TABLES_SQL)

            ollama_ok = _check_ollama()
            if not ollama_ok:
                skipped_vectors = True
                logger.warning("Ollama unreachable — rebuilding FTS only")

            for msg_id, session_id, role, content, created_at in messages:
                try:
                    conn.execute(
                        "INSERT INTO message_fts (content, role, session_id, message_id, created_at) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (content, role, session_id, msg_id, created_at),
                    )
                    if ollama_ok:
                        embedding = _embed_sync(content)
                        if embedding:
                            conn.execute(
                                "INSERT INTO message_vec (embedding, content, role, session_id, message_id, created_at) "
                                "VALUES (?, ?, ?, ?, ?, ?)",
                                (json.dumps(embedding), content, role, session_id, msg_id, created_at),
                            )
                        else:
                            skipped_vectors = True
                    indexed += 1
                    # Commit every 50 to allow recovery from interruption
                    if indexed % 50 == 0:
                        conn.commit()
                except Exception as e:
                    logger.warning("Rebuild: failed to index %s: %s", msg_id, e)
                    errors += 1

            conn.commit()
            return {"indexed": indexed, "errors": errors, "skipped_vectors": skipped_vectors,
                    "total_source": len(messages)}
        finally:
            conn.close()

    return await _run_worker_op(_do_rebuild)


# ---------------------------------------------------------------------------
# Memory files
# ---------------------------------------------------------------------------


@router.get("/agents/{agent_id}/memory-files")
async def list_memory_files(agent_id: str):
    """List memory files for an agent."""
    await _validate_agent(agent_id)
    memory_dir = DATA_DIR / "agents" / agent_id / "memory"
    if not memory_dir.is_dir():
        return []

    files = []
    for f in sorted(memory_dir.iterdir()):
        if not f.is_file():
            continue
        stat = f.stat()
        content = f.read_text(errors="replace")
        files.append({
            "name": f.name,
            "size": stat.st_size,
            "modified_at": time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime(stat.st_mtime),
            ),
            "content_preview": content[:200],
            "content": content,
        })
    return files


@router.delete("/agents/{agent_id}/memory-files/{filename}")
async def delete_memory_file(agent_id: str, filename: str):
    """Delete a memory file from disk and the worker DB's memory_files table."""
    await _validate_agent(agent_id)

    # Prevent path traversal
    if "/" in filename or "\\" in filename or filename.startswith("."):
        raise HTTPException(status_code=400, detail="Invalid filename")

    memory_dir = DATA_DIR / "agents" / agent_id / "memory"
    file_path = memory_dir / filename
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="Memory file not found")

    file_path.unlink()

    # Also remove from worker DB memory_files table
    def _clean_db():
        try:
            conn = _open_worker_db(agent_id)
            try:
                conn.execute(
                    "DELETE FROM memory_files WHERE file_path = ?",
                    (f"memory/{filename}",),
                )
                conn.commit()
            finally:
                conn.close()
        except FileNotFoundError:
            pass  # No worker DB yet — that's fine

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _clean_db)
    return {"deleted": filename}
