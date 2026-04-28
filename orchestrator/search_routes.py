"""Search index management API routes.

Provides endpoints to inspect, edit, delete, and rebuild the per-agent
memory search indexes (memory_fts / memory_vec) stored in worker databases.
Also exposes memory file management for viewing and deleting agent memory files.

The orchestrator opens worker databases directly (synchronous sqlite3
via run_in_executor) — this is the only place where the orchestrator
reaches into worker DB files.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import time
import urllib.error
import urllib.request
import asyncio
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

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

MEMORY_TABLES_SQL = """\
CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
    content,
    file_path UNINDEXED,
    chunk_key UNINDEXED,
    session_ref UNINDEXED,
    created_at UNINDEXED,
    tokenize = 'porter'
);

CREATE VIRTUAL TABLE IF NOT EXISTS memory_vec USING vec0(
    embedding float[768],
    +content TEXT,
    +file_path TEXT,
    +chunk_key TEXT,
    +session_ref TEXT,
    +created_at TEXT
);

CREATE TABLE IF NOT EXISTS memory_vec_map (
    chunk_key TEXT NOT NULL PRIMARY KEY,
    vec_rowid INTEGER NOT NULL
);
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _open_worker_db(host_dir: str | Path) -> sqlite3.Connection:
    """Open a synchronous connection to an agent's worker database."""
    path = Path(host_dir) / "worker_db.sqlite"
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


async def _validate_agent(agent_id: str) -> Path:
    """Raise 404 if agent doesn't exist. Returns host_dir Path."""
    db = await get_db()
    async with db.execute(
        "SELECT host_dir FROM agents WHERE id = ? AND status = 'active'",
        (agent_id,),
    ) as cur:
        row = await cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Agent not found")
    return Path(row[0])


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


def _extract_iso_ts(session_ref: str) -> str:
    """Extract an ISO timestamp from the start of session_ref, or empty string."""
    if len(session_ref) >= 20 and session_ref[10] == "T" and session_ref[19] == "Z":
        return session_ref[:20]
    return ""


def _parse_memory_chunks(file_path: str, content: str) -> list[dict[str, str]]:
    """Split a memory file into per-session chunks.

    Mirrors worker/search.py parse_memory_chunks() — duplicated here because
    the orchestrator cannot import worker code.
    """
    parts = re.split(r"(?=^## Session: )", content, flags=re.MULTILINE)
    chunks: list[dict[str, str]] = []

    for i, part in enumerate(parts):
        part = part.strip()
        if not part:
            continue

        header_match = re.match(r"^## Session:\s*(.+)", part)
        if header_match:
            session_ref = header_match.group(1).strip()
            body = re.sub(r"^## Session:.+\n*", "", part).strip().rstrip("-").strip()
        else:
            session_ref = ""
            body = part

        if not body:
            continue

        chunks.append({
            "chunk_key": f"{file_path}#{i}",
            "file_path": file_path,
            "session_ref": session_ref,
            "created_at": _extract_iso_ts(session_ref),
            "content": body,
        })

    return chunks


# ---------------------------------------------------------------------------
# Reindex a single memory file (callable from other modules)
# ---------------------------------------------------------------------------


async def reindex_memory_file(agent_id: str, rel_path: str, content: str) -> None:
    """Re-index a memory file's chunks into memory_fts/memory_vec.

    Called after a memory file is written to disk, from any endpoint.
    Silently skips if the worker DB doesn't exist yet.
    """
    db = await get_db()
    async with db.execute(
        "SELECT host_dir FROM agents WHERE id = ?", (agent_id,),
    ) as cur:
        row = await cur.fetchone()
    if not row:
        return
    host_dir = Path(row[0])

    def _do():
        try:
            conn = _open_worker_db(host_dir)
        except FileNotFoundError:
            return
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        try:
            # Ensure tables exist
            conn.executescript(MEMORY_TABLES_SQL)

            # Delete old FTS entries for this file
            conn.execute(
                "DELETE FROM memory_fts WHERE rowid IN ("
                "  SELECT rowid FROM memory_fts WHERE file_path = ?"
                ")",
                (rel_path,),
            )
            # Delete old vec entries via mapping table
            rows = conn.execute(
                "SELECT chunk_key, vec_rowid FROM memory_vec_map "
                "WHERE chunk_key LIKE ?",
                (f"{rel_path}#%",),
            ).fetchall()
            for chunk_key, vec_rowid in rows:
                try:
                    conn.execute("DELETE FROM memory_vec WHERE rowid = ?", (vec_rowid,))
                except sqlite3.OperationalError:
                    pass
                conn.execute("DELETE FROM memory_vec_map WHERE chunk_key = ?", (chunk_key,))

            # Re-index chunks
            chunks = _parse_memory_chunks(rel_path, content)
            ollama_ok = _check_ollama()
            for chunk in chunks:
                ck = chunk["chunk_key"]
                ts = chunk["created_at"] or now
                conn.execute(
                    "INSERT INTO memory_fts "
                    "(content, file_path, chunk_key, session_ref, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (chunk["content"], rel_path, ck, chunk["session_ref"], ts),
                )
                if ollama_ok:
                    embedding = _embed_sync(chunk["content"])
                    if embedding:
                        conn.execute(
                            "INSERT INTO memory_vec "
                            "(embedding, content, file_path, chunk_key, session_ref, created_at) "
                            "VALUES (?, ?, ?, ?, ?, ?)",
                            (json.dumps(embedding), chunk["content"], rel_path,
                             ck, chunk["session_ref"], ts),
                        )
                        vec_rowid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                        conn.execute(
                            "INSERT OR REPLACE INTO memory_vec_map (chunk_key, vec_rowid) "
                            "VALUES (?, ?)",
                            (ck, vec_rowid),
                        )
            conn.commit()
        finally:
            conn.close()

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _do)


# ---------------------------------------------------------------------------
# Search / List
# ---------------------------------------------------------------------------


@router.get("/search-index")
async def search_index(
    agents: list[str] = Query(..., description="Agent names to search"),
    q: str = "",
    limit: int = 50,
):
    """Search memory FTS indexes for the given agents.

    Accepts one or more agent names via repeated `agents` query params.
    Single agent: ``?agents=MyAgent&q=hello``
    All agents:   ``?agents=AgentA&agents=AgentB&q=hello``
    """
    if not agents:
        raise HTTPException(status_code=400, detail="At least one agent name required")

    # Resolve names → (id, name) pairs
    db = await get_db()
    placeholders = ", ".join("?" for _ in agents)
    async with db.execute(
        f"SELECT id, name, host_dir FROM agents WHERE status = 'active' AND name IN ({placeholders})",
        agents,
    ) as cur:
        agent_rows = await cur.fetchall()

    if not agent_rows:
        raise HTTPException(status_code=404, detail="No matching active agents found")

    def _query():
        all_results: list[dict] = []
        cap = min(limit, 200)
        for agent_id, agent_name, host_dir in agent_rows:
            try:
                conn = _open_worker_db(host_dir)
            except FileNotFoundError:
                continue
            try:
                if q.strip():
                    fts_query = _sanitize_fts5_query(q)
                    rows = conn.execute(
                        "SELECT chunk_key, content, file_path, session_ref, created_at, rank "
                        "FROM memory_fts WHERE memory_fts MATCH ? "
                        "ORDER BY rank LIMIT ?",
                        (fts_query, cap),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT chunk_key, content, file_path, session_ref, created_at, 0.0 "
                        "FROM memory_fts ORDER BY rowid DESC LIMIT ?",
                        (cap,),
                    ).fetchall()
                for r in rows:
                    all_results.append({
                        "chunk_key": r[0], "content": r[1], "file_path": r[2],
                        "session_ref": r[3], "created_at": r[4], "rank": r[5],
                        "agent_id": agent_id, "agent_name": agent_name,
                    })
            finally:
                conn.close()
        if q.strip():
            all_results.sort(key=lambda x: x["rank"])
        return all_results[:cap]

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _query)


# ---------------------------------------------------------------------------
# Stats (must be before {chunk_key} to avoid path parameter capture)
# ---------------------------------------------------------------------------


@router.get("/agents/{agent_id}/search-index/stats")
async def index_stats(agent_id: str):
    """Return index health stats: counts for memory files, FTS, and vec."""
    host_dir = await _validate_agent(agent_id)

    # Count memory files on disk
    memory_dir = host_dir / "memory"
    memory_files_count = 0
    if memory_dir.is_dir():
        memory_files_count = sum(1 for f in memory_dir.iterdir() if f.is_file() and f.suffix == ".md")

    def _worker_stats():
        conn = _open_worker_db(host_dir)
        try:
            try:
                fts_count = conn.execute("SELECT COUNT(*) FROM memory_fts").fetchone()[0]
            except sqlite3.OperationalError:
                fts_count = 0
            try:
                vec_count = conn.execute("SELECT COUNT(*) FROM memory_vec").fetchone()[0]
            except sqlite3.OperationalError:
                vec_count = 0
            return {"fts_count": fts_count, "vec_count": vec_count}
        finally:
            conn.close()

    worker = await _run_worker_op(_worker_stats)
    return {
        "memory_files_count": memory_files_count,
        "fts_count": worker["fts_count"],
        "vec_count": worker["vec_count"],
    }


# ---------------------------------------------------------------------------
# Reindex (must be before {chunk_key} to avoid path parameter capture)
# ---------------------------------------------------------------------------


@router.post("/agents/{agent_id}/search-index/reindex")
async def reindex(agent_id: str, req: ReindexRequest | None = None):
    """Reindex specific chunks or perform a full rebuild from memory files on disk."""
    host_dir = await _validate_agent(agent_id)

    if req and req.chunk_keys:
        return await _reindex_chunks(host_dir, req.chunk_keys)

    return await _full_rebuild(host_dir)


# ---------------------------------------------------------------------------
# Single entry detail
# ---------------------------------------------------------------------------


@router.get("/agents/{agent_id}/search-index/{chunk_key:path}")
async def get_index_entry(agent_id: str, chunk_key: str):
    """Get full details of a single indexed entry."""
    host_dir = await _validate_agent(agent_id)

    def _query():
        conn = _open_worker_db(host_dir)
        try:
            row = conn.execute(
                "SELECT chunk_key, content, file_path, session_ref, created_at "
                "FROM memory_fts WHERE chunk_key = ? LIMIT 1",
                (chunk_key,),
            ).fetchone()
            if not row:
                return None

            vec_row = conn.execute(
                "SELECT vec_rowid FROM memory_vec_map WHERE chunk_key = ?",
                (chunk_key,),
            ).fetchone()
            return {
                "chunk_key": row[0], "content": row[1], "file_path": row[2],
                "session_ref": row[3], "created_at": row[4],
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


@router.put("/agents/{agent_id}/search-index/{chunk_key:path}")
async def update_index_entry(
    agent_id: str, chunk_key: str, req: SearchIndexUpdateRequest,
):
    """Update content in memory FTS and vec indexes."""
    host_dir = await _validate_agent(agent_id)

    def _update():
        conn = _open_worker_db(host_dir)
        try:
            # Get existing row metadata
            row = conn.execute(
                "SELECT file_path, session_ref, created_at FROM memory_fts "
                "WHERE chunk_key = ? LIMIT 1",
                (chunk_key,),
            ).fetchone()
            if not row:
                return {"error": "not_found"}

            file_path, session_ref, created_at = row

            # Delete old FTS entry and insert new
            conn.execute(
                "DELETE FROM memory_fts WHERE rowid IN ("
                "  SELECT rowid FROM memory_fts WHERE chunk_key = ?"
                ")",
                (chunk_key,),
            )
            conn.execute(
                "INSERT INTO memory_fts (content, file_path, chunk_key, session_ref, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (req.content, file_path, chunk_key, session_ref, created_at),
            )

            # Delete old vec entry via mapping table and re-embed
            vec_warning = None
            map_row = conn.execute(
                "SELECT vec_rowid FROM memory_vec_map WHERE chunk_key = ?",
                (chunk_key,),
            ).fetchone()
            if map_row:
                try:
                    conn.execute("DELETE FROM memory_vec WHERE rowid = ?", (map_row[0],))
                except sqlite3.OperationalError:
                    pass
                conn.execute(
                    "DELETE FROM memory_vec_map WHERE chunk_key = ?", (chunk_key,),
                )

            embedding = _embed_sync(req.content)
            if embedding:
                conn.execute(
                    "INSERT INTO memory_vec "
                    "(embedding, content, file_path, chunk_key, session_ref, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (json.dumps(embedding), req.content, file_path,
                     chunk_key, session_ref, created_at),
                )
                vec_rowid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                conn.execute(
                    "INSERT OR REPLACE INTO memory_vec_map (chunk_key, vec_rowid) "
                    "VALUES (?, ?)",
                    (chunk_key, vec_rowid),
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


@router.delete("/agents/{agent_id}/search-index/{chunk_key:path}")
async def delete_index_entry(agent_id: str, chunk_key: str):
    """Delete an entry from memory FTS and vec indexes."""
    host_dir = await _validate_agent(agent_id)

    def _delete():
        conn = _open_worker_db(host_dir)
        try:
            fts_deleted = conn.execute(
                "DELETE FROM memory_fts WHERE rowid IN ("
                "  SELECT rowid FROM memory_fts WHERE chunk_key = ?"
                ")",
                (chunk_key,),
            ).rowcount

            # Delete vec via mapping table
            vec_deleted = 0
            map_row = conn.execute(
                "SELECT vec_rowid FROM memory_vec_map WHERE chunk_key = ?",
                (chunk_key,),
            ).fetchone()
            if map_row:
                try:
                    conn.execute("DELETE FROM memory_vec WHERE rowid = ?", (map_row[0],))
                    vec_deleted = 1
                except sqlite3.OperationalError:
                    pass
                conn.execute(
                    "DELETE FROM memory_vec_map WHERE chunk_key = ?", (chunk_key,),
                )

            conn.commit()
            return {"fts_deleted": fts_deleted, "vec_deleted": vec_deleted}
        finally:
            conn.close()

    return await _run_worker_op(_delete)


# ---------------------------------------------------------------------------
# Reindex helpers
# ---------------------------------------------------------------------------


async def _reindex_chunks(host_dir: Path, chunk_keys: list[str]):
    """Reindex specific chunks by re-reading their source memory files."""
    # Determine which files to read
    file_paths = set()
    for ck in chunk_keys:
        if "#" in ck:
            file_paths.add(ck.rsplit("#", 1)[0])

    def _do_reindex():
        conn = _open_worker_db(host_dir)
        indexed = 0
        errors = 0
        skipped_vectors = False
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        try:
            for fp in file_paths:
                abs_path = host_dir / fp
                if not abs_path.is_file():
                    errors += 1
                    continue

                content = abs_path.read_text()
                chunks = _parse_memory_chunks(fp, content)
                target_keys = {ck for ck in chunk_keys if ck.startswith(fp + "#")}

                for chunk in chunks:
                    if chunk["chunk_key"] not in target_keys:
                        continue
                    try:
                        ck = chunk["chunk_key"]
                        # Delete old FTS
                        conn.execute(
                            "DELETE FROM memory_fts WHERE rowid IN ("
                            "  SELECT rowid FROM memory_fts WHERE chunk_key = ?"
                            ")", (ck,),
                        )
                        # Insert new FTS
                        ts = chunk["created_at"] or now
                        conn.execute(
                            "INSERT INTO memory_fts "
                            "(content, file_path, chunk_key, session_ref, created_at) "
                            "VALUES (?, ?, ?, ?, ?)",
                            (chunk["content"], fp, ck, chunk["session_ref"], ts),
                        )
                        # Delete old vec via map
                        map_row = conn.execute(
                            "SELECT vec_rowid FROM memory_vec_map WHERE chunk_key = ?",
                            (ck,),
                        ).fetchone()
                        if map_row:
                            try:
                                conn.execute(
                                    "DELETE FROM memory_vec WHERE rowid = ?",
                                    (map_row[0],),
                                )
                            except sqlite3.OperationalError:
                                pass
                            conn.execute(
                                "DELETE FROM memory_vec_map WHERE chunk_key = ?",
                                (ck,),
                            )
                        # Re-embed
                        embedding = _embed_sync(chunk["content"])
                        if embedding:
                            conn.execute(
                                "INSERT INTO memory_vec "
                                "(embedding, content, file_path, chunk_key, session_ref, created_at) "
                                "VALUES (?, ?, ?, ?, ?, ?)",
                                (json.dumps(embedding), chunk["content"], fp,
                                 ck, chunk["session_ref"], ts),
                            )
                            vec_rowid = conn.execute(
                                "SELECT last_insert_rowid()"
                            ).fetchone()[0]
                            conn.execute(
                                "INSERT OR REPLACE INTO memory_vec_map "
                                "(chunk_key, vec_rowid) VALUES (?, ?)",
                                (ck, vec_rowid),
                            )
                        else:
                            skipped_vectors = True
                        indexed += 1
                    except Exception as e:
                        logger.warning("Reindex failed for %s: %s", chunk["chunk_key"], e)
                        errors += 1

            conn.commit()
            return {"indexed": indexed, "errors": errors, "skipped_vectors": skipped_vectors}
        finally:
            conn.close()

    return await _run_worker_op(_do_reindex)


async def _full_rebuild(host_dir: Path):
    """Drop and recreate memory indexes, re-index all memory files from disk."""
    memory_dir = host_dir / "memory"

    # Collect all memory files
    memory_files: list[tuple[str, str]] = []  # (rel_path, content)
    if memory_dir.is_dir():
        for md_file in sorted(memory_dir.iterdir()):
            if md_file.is_file() and md_file.suffix == ".md":
                rel_path = f"memory/{md_file.name}"
                memory_files.append((rel_path, md_file.read_text()))

    def _do_rebuild():
        conn = _open_worker_db(host_dir)
        indexed = 0
        errors = 0
        skipped_vectors = False
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        try:
            # Drop and recreate tables
            conn.execute("DROP TABLE IF EXISTS memory_fts")
            conn.execute("DROP TABLE IF EXISTS memory_vec")
            conn.execute("DROP TABLE IF EXISTS memory_vec_map")
            conn.executescript(MEMORY_TABLES_SQL)

            ollama_ok = _check_ollama()
            if not ollama_ok:
                skipped_vectors = True
                logger.warning("Ollama unreachable — rebuilding FTS only")

            for rel_path, content in memory_files:
                chunks = _parse_memory_chunks(rel_path, content)
                for chunk in chunks:
                    try:
                        ts = chunk["created_at"] or now
                        conn.execute(
                            "INSERT INTO memory_fts "
                            "(content, file_path, chunk_key, session_ref, created_at) "
                            "VALUES (?, ?, ?, ?, ?)",
                            (chunk["content"], rel_path, chunk["chunk_key"],
                             chunk["session_ref"], ts),
                        )
                        if ollama_ok:
                            embedding = _embed_sync(chunk["content"])
                            if embedding:
                                conn.execute(
                                    "INSERT INTO memory_vec "
                                    "(embedding, content, file_path, chunk_key, "
                                    "session_ref, created_at) "
                                    "VALUES (?, ?, ?, ?, ?, ?)",
                                    (json.dumps(embedding), chunk["content"],
                                     rel_path, chunk["chunk_key"],
                                     chunk["session_ref"], ts),
                                )
                                vec_rowid = conn.execute(
                                    "SELECT last_insert_rowid()"
                                ).fetchone()[0]
                                conn.execute(
                                    "INSERT INTO memory_vec_map "
                                    "(chunk_key, vec_rowid) VALUES (?, ?)",
                                    (chunk["chunk_key"], vec_rowid),
                                )
                            else:
                                skipped_vectors = True
                        indexed += 1
                        if indexed % 50 == 0:
                            conn.commit()
                    except Exception as e:
                        logger.warning(
                            "Rebuild: failed to index %s: %s",
                            chunk["chunk_key"], e,
                        )
                        errors += 1

            conn.commit()
            return {
                "indexed": indexed, "errors": errors,
                "skipped_vectors": skipped_vectors,
                "total_source": len(memory_files),
            }
        finally:
            conn.close()

    return await _run_worker_op(_do_rebuild)


# ---------------------------------------------------------------------------
# Memory files
# ---------------------------------------------------------------------------


@router.get("/agents/{agent_id}/memory-files")
async def list_memory_files(agent_id: str):
    """List memory files for an agent."""
    host_dir = await _validate_agent(agent_id)
    memory_dir = host_dir / "memory"
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
    """Delete a memory file from disk, the memory_files table, and search indexes."""
    host_dir = await _validate_agent(agent_id)

    # Prevent path traversal
    if "/" in filename or "\\" in filename or filename.startswith("."):
        raise HTTPException(status_code=400, detail="Invalid filename")

    memory_dir = host_dir / "memory"
    file_path = memory_dir / filename
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="Memory file not found")

    file_path.unlink()
    rel_path = f"memory/{filename}"

    def _clean_db():
        try:
            conn = _open_worker_db(host_dir)
            try:
                # Remove from memory_files table
                conn.execute(
                    "DELETE FROM memory_files WHERE file_path = ?",
                    (rel_path,),
                )
                # Remove from memory_fts
                conn.execute(
                    "DELETE FROM memory_fts WHERE rowid IN ("
                    "  SELECT rowid FROM memory_fts WHERE file_path = ?"
                    ")",
                    (rel_path,),
                )
                # Remove from memory_vec via mapping table
                rows = conn.execute(
                    "SELECT chunk_key, vec_rowid FROM memory_vec_map "
                    "WHERE chunk_key LIKE ?",
                    (f"{rel_path}#%",),
                ).fetchall()
                for chunk_key, vec_rowid in rows:
                    try:
                        conn.execute(
                            "DELETE FROM memory_vec WHERE rowid = ?",
                            (vec_rowid,),
                        )
                    except sqlite3.OperationalError:
                        pass
                    conn.execute(
                        "DELETE FROM memory_vec_map WHERE chunk_key = ?",
                        (chunk_key,),
                    )
                conn.commit()
            finally:
                conn.close()
        except FileNotFoundError:
            pass  # No worker DB yet — that's fine

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _clean_db)
    return {"deleted": filename}
