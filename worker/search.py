"""Hybrid search: FTS5 (BM25) + sqlite-vec (vector) with RRF merge."""

import json
import sqlite3
import sys
import time
from typing import Any

from worker.embed import embed

EMBEDDING_DIM = 768
RRF_K = 60
SEARCH_TOP_K = 20
SEARCH_RESULTS = 10


def index_message(
    conn: sqlite3.Connection,
    message_id: str,
    session_id: str,
    role: str,
    content: str,
) -> None:
    """Index a message into FTS5 and (if Ollama is available) vec0."""
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    # Always index into FTS5 — no external dependency
    conn.execute(
        "INSERT INTO message_fts (content, role, session_id, message_id, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (content, role, session_id, message_id, now),
    )
    conn.commit()

    return message_id, now


async def index_vector(
    conn: sqlite3.Connection,
    message_id: str,
    session_id: str,
    role: str,
    content: str,
    created_at: str,
) -> None:
    """Index a message into vec0. Called separately since it's async."""
    try:
        vec = await embed(content)
        conn.execute(
            "INSERT INTO message_vec (embedding, content, role, session_id, message_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (json.dumps(vec), content, role, session_id, message_id, created_at),
        )
        conn.commit()
    except Exception as e:
        sys.stderr.write(f"search: vector indexing failed: {e}\n")
        sys.stderr.flush()


def _sanitize_fts5_query(text: str) -> str:
    """Escape special FTS5 characters by quoting each word."""
    import re
    words = re.findall(r'\w+', text)
    if not words:
        return '""'
    return " OR ".join(f'"{w}"' for w in words)


def search_bm25(
    conn: sqlite3.Connection, query_text: str, limit: int = SEARCH_TOP_K,
    exclude_session_id: str | None = None,
) -> list[dict[str, Any]]:
    """Full-text search via FTS5 BM25 ranking."""
    fts_query = _sanitize_fts5_query(query_text)
    if exclude_session_id:
        rows = conn.execute(
            "SELECT message_id, content, role, session_id, created_at, rank "
            "FROM message_fts WHERE message_fts MATCH ? AND session_id != ? "
            "ORDER BY rank LIMIT ?",
            (fts_query, exclude_session_id, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT message_id, content, role, session_id, created_at, rank "
            "FROM message_fts WHERE message_fts MATCH ? "
            "ORDER BY rank LIMIT ?",
            (fts_query, limit),
        ).fetchall()
    return [
        {
            "message_id": r[0], "content": r[1], "role": r[2],
            "session_id": r[3], "created_at": r[4], "score": r[5],
        }
        for r in rows
    ]


async def search_vector(
    conn: sqlite3.Connection, query_text: str, limit: int = SEARCH_TOP_K,
    exclude_session_id: str | None = None,
) -> list[dict[str, Any]] | None:
    """Vector similarity search via sqlite-vec. Returns None if Ollama is unavailable."""
    try:
        query_vec = await embed(query_text)
    except Exception as e:
        sys.stderr.write(f"search: vector search skipped (Ollama down): {e}\n")
        sys.stderr.flush()
        return None

    if exclude_session_id:
        rows = conn.execute(
            "SELECT content, role, session_id, message_id, created_at, distance "
            "FROM message_vec WHERE embedding MATCH ? AND session_id != ? "
            "ORDER BY distance LIMIT ?",
            (json.dumps(query_vec), exclude_session_id, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT content, role, session_id, message_id, created_at, distance "
            "FROM message_vec WHERE embedding MATCH ? "
            "ORDER BY distance LIMIT ?",
            (json.dumps(query_vec), limit),
        ).fetchall()
    return [
        {
            "message_id": r[3], "content": r[0], "role": r[1],
            "session_id": r[2], "created_at": r[4], "score": r[5],
        }
        for r in rows
    ]


async def search_hybrid(
    conn: sqlite3.Connection, query_text: str, limit: int = SEARCH_RESULTS,
    exclude_session_id: str | None = None,
) -> list[dict[str, Any]]:
    """Hybrid search: BM25 + vector, merged with Reciprocal Rank Fusion."""
    bm25_results = search_bm25(conn, query_text, exclude_session_id=exclude_session_id)
    vec_results = await search_vector(conn, query_text, exclude_session_id=exclude_session_id)

    if vec_results is None:
        # Ollama down — BM25 only
        return bm25_results[:limit]

    # RRF merge: score(doc) = sum(1 / (k + rank)) across both result lists
    rrf_scores: dict[str, float] = {}
    doc_map: dict[str, dict] = {}

    for rank, doc in enumerate(bm25_results, start=1):
        mid = doc["message_id"]
        rrf_scores[mid] = rrf_scores.get(mid, 0) + 1 / (RRF_K + rank)
        doc_map[mid] = doc

    for rank, doc in enumerate(vec_results, start=1):
        mid = doc["message_id"]
        rrf_scores[mid] = rrf_scores.get(mid, 0) + 1 / (RRF_K + rank)
        doc_map[mid] = doc

    sorted_ids = sorted(rrf_scores, key=lambda mid: rrf_scores[mid], reverse=True)
    return [doc_map[mid] for mid in sorted_ids[:limit]]


def format_context(results: list[dict[str, Any]], max_chars: int = 2000) -> str | None:
    """Format search results into a context string for injection into the system prompt."""
    if not results:
        return None

    parts: list[str] = []
    total = 0
    for r in results:
        entry = f"[{r['role']}]: {r['content']}"
        if total + len(entry) > max_chars:
            remaining = max_chars - total
            if remaining > 100:
                parts.append(entry[:remaining] + "...")
            break
        parts.append(entry)
        total += len(entry)

    return "\n\n".join(parts) if parts else None
