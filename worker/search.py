"""Hybrid search: FTS5 (BM25) + sqlite-vec (vector) with RRF merge.

Searches session summaries stored in memory_fts / memory_vec tables.
Individual messages are no longer indexed — only distilled session
summaries from daily memory files are searchable.
"""

import json
import re
import sqlite3
import sys
import time
from typing import Any

from worker.embed import embed

EMBEDDING_DIM = 768
RRF_K = 60
SEARCH_TOP_K = 20
SEARCH_RESULTS = 10


# ---------------------------------------------------------------------------
# Memory file parsing
# ---------------------------------------------------------------------------


def parse_memory_chunks(file_path: str, content: str) -> list[dict[str, str]]:
    """Split a memory file into per-session chunks for indexing.

    Daily memory files use ``## Session: <path>`` headers to delimit
    individual session summaries.  Each chunk gets a unique key like
    ``memory/2026-04-07.md#0``.

    Compacted files (produced by ``compact_memory_files``) have a single
    ``## Compacted Memory`` header and are indexed as one chunk.
    """
    # Split on ## Session: headers, keeping the header text
    parts = re.split(r"(?=^## Session: )", content, flags=re.MULTILINE)
    chunks: list[dict[str, str]] = []

    for i, part in enumerate(parts):
        part = part.strip()
        if not part:
            continue

        # Extract session reference from header
        header_match = re.match(r"^## Session:\s*(.+)", part)
        if header_match:
            session_ref = header_match.group(1).strip()
            # Body is everything after the header line, strip trailing ---
            body = re.sub(r"^## Session:.+\n*", "", part).strip().rstrip("-").strip()
        else:
            # Compacted file or no session headers
            session_ref = "compacted"
            body = part

        if not body:
            continue

        chunks.append({
            "chunk_key": f"{file_path}#{i}",
            "file_path": file_path,
            "session_ref": session_ref,
            "content": body,
        })

    return chunks


# ---------------------------------------------------------------------------
# Memory indexing
# ---------------------------------------------------------------------------


def index_memory_file(
    conn: sqlite3.Connection, file_path: str, content: str,
) -> int:
    """Index a memory file's session chunks into memory_fts.

    Deletes any existing FTS entries for this file_path before inserting.
    Returns the number of chunks indexed.
    """
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    chunks = parse_memory_chunks(file_path, content)

    # Delete old entries for this file
    conn.execute(
        "DELETE FROM memory_fts WHERE rowid IN ("
        "  SELECT rowid FROM memory_fts WHERE file_path = ?"
        ")",
        (file_path,),
    )

    for chunk in chunks:
        conn.execute(
            "INSERT INTO memory_fts (content, file_path, chunk_key, session_ref, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (chunk["content"], file_path, chunk["chunk_key"],
             chunk["session_ref"], now),
        )

    conn.commit()
    return len(chunks)


async def index_memory_vectors(
    conn: sqlite3.Connection, file_path: str, content: str,
) -> int:
    """Index a memory file's session chunks into memory_vec.

    Uses memory_vec_map for rowid tracking since vec0 doesn't support
    WHERE on auxiliary columns.  Non-fatal on embedding failure.
    Returns the number of chunks embedded.
    """
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    chunks = parse_memory_chunks(file_path, content)
    embedded = 0

    try:
        for chunk in chunks:
            chunk_key = chunk["chunk_key"]

            # Delete old vec entry via rowid map
            row = conn.execute(
                "SELECT vec_rowid FROM memory_vec_map WHERE chunk_key = ?",
                (chunk_key,),
            ).fetchone()
            if row:
                try:
                    conn.execute("DELETE FROM memory_vec WHERE rowid = ?", (row[0],))
                except sqlite3.OperationalError:
                    pass
                conn.execute(
                    "DELETE FROM memory_vec_map WHERE chunk_key = ?",
                    (chunk_key,),
                )

            # Embed and insert
            vec = await embed(chunk["content"])
            conn.execute(
                "INSERT INTO memory_vec "
                "(embedding, content, file_path, chunk_key, session_ref, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (json.dumps(vec), chunk["content"], file_path,
                 chunk_key, chunk["session_ref"], now),
            )
            # Record the rowid for future deletion
            vec_rowid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            conn.execute(
                "INSERT OR REPLACE INTO memory_vec_map (chunk_key, vec_rowid) "
                "VALUES (?, ?)",
                (chunk_key, vec_rowid),
            )
            embedded += 1

        conn.commit()
    except Exception as e:
        sys.stderr.write(f"search: memory vector indexing failed: {e}\n")
        sys.stderr.flush()
        conn.commit()  # commit whatever succeeded

    return embedded


def delete_memory_index(conn: sqlite3.Connection, file_path: str) -> None:
    """Delete all index entries (FTS + vec) for a memory file."""
    # FTS: file_path is an unindexed column but we can still filter on it
    conn.execute(
        "DELETE FROM memory_fts WHERE rowid IN ("
        "  SELECT rowid FROM memory_fts WHERE file_path = ?"
        ")",
        (file_path,),
    )

    # Vec: use the mapping table to find rowids
    rows = conn.execute(
        "SELECT chunk_key, vec_rowid FROM memory_vec_map "
        "WHERE chunk_key LIKE ?",
        (f"{file_path}#%",),
    ).fetchall()
    for chunk_key, vec_rowid in rows:
        try:
            conn.execute("DELETE FROM memory_vec WHERE rowid = ?", (vec_rowid,))
        except sqlite3.OperationalError:
            pass
        conn.execute(
            "DELETE FROM memory_vec_map WHERE chunk_key = ?", (chunk_key,),
        )

    conn.commit()


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


def _sanitize_fts5_query(text: str) -> str:
    """Escape special FTS5 characters by quoting each word."""
    words = re.findall(r'\w+', text)
    if not words:
        return '""'
    return " OR ".join(f'"{w}"' for w in words)


def search_bm25(
    conn: sqlite3.Connection, query_text: str, limit: int = SEARCH_TOP_K,
) -> list[dict[str, Any]]:
    """Full-text search via FTS5 BM25 ranking on memory summaries."""
    fts_query = _sanitize_fts5_query(query_text)
    rows = conn.execute(
        "SELECT chunk_key, content, file_path, session_ref, created_at, rank "
        "FROM memory_fts WHERE memory_fts MATCH ? "
        "ORDER BY rank LIMIT ?",
        (fts_query, limit),
    ).fetchall()
    return [
        {
            "chunk_key": r[0], "content": r[1], "file_path": r[2],
            "session_ref": r[3], "created_at": r[4], "score": r[5],
        }
        for r in rows
    ]


async def search_vector(
    conn: sqlite3.Connection, query_text: str, limit: int = SEARCH_TOP_K,
) -> list[dict[str, Any]] | None:
    """Vector similarity search on memory summaries. Returns None if Ollama is unavailable."""
    try:
        query_vec = await embed(query_text)
    except Exception as e:
        sys.stderr.write(f"search: vector search skipped (Ollama down): {e}\n")
        sys.stderr.flush()
        return None

    rows = conn.execute(
        "SELECT content, file_path, chunk_key, session_ref, created_at, distance "
        "FROM memory_vec WHERE embedding MATCH ? "
        "ORDER BY distance LIMIT ?",
        (json.dumps(query_vec), limit),
    ).fetchall()
    return [
        {
            "chunk_key": r[2], "content": r[0], "file_path": r[1],
            "session_ref": r[3], "created_at": r[4], "score": r[5],
        }
        for r in rows
    ]


async def search_hybrid(
    conn: sqlite3.Connection, query_text: str, limit: int = SEARCH_RESULTS,
) -> list[dict[str, Any]]:
    """Hybrid search: BM25 + vector, merged with Reciprocal Rank Fusion."""
    bm25_results = search_bm25(conn, query_text)
    vec_results = await search_vector(conn, query_text)

    if vec_results is None:
        # Ollama down — BM25 only
        return bm25_results[:limit]

    # RRF merge: score(doc) = sum(1 / (k + rank)) across both result lists
    rrf_scores: dict[str, float] = {}
    doc_map: dict[str, dict] = {}

    for rank, doc in enumerate(bm25_results, start=1):
        key = doc["chunk_key"]
        rrf_scores[key] = rrf_scores.get(key, 0) + 1 / (RRF_K + rank)
        doc_map[key] = doc

    for rank, doc in enumerate(vec_results, start=1):
        key = doc["chunk_key"]
        rrf_scores[key] = rrf_scores.get(key, 0) + 1 / (RRF_K + rank)
        doc_map[key] = doc

    sorted_keys = sorted(rrf_scores, key=lambda k: rrf_scores[k], reverse=True)
    return [doc_map[k] for k in sorted_keys[:limit]]


def format_context(results: list[dict[str, Any]], max_chars: int = 2000) -> str | None:
    """Format search results into a context string for the system prompt."""
    if not results:
        return None

    parts: list[str] = []
    total = 0
    for r in results:
        entry = r["content"]
        if total + len(entry) > max_chars:
            remaining = max_chars - total
            if remaining > 100:
                parts.append(entry[:remaining] + "...")
            break
        parts.append(entry)
        total += len(entry)

    return "\n\n".join(parts) if parts else None
