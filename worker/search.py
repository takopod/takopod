"""Hybrid search: FTS5 (BM25) + sqlite-vec (vector) with RRF merge.

Searches session summaries stored in memory_fts / memory_vec tables.
Individual messages are no longer indexed — only distilled session
summaries from daily memory files are searchable.
"""

import json
import logging
import re
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

from worker.embed import embed

EMBEDDING_DIM = 768
RRF_K = 60
SEARCH_TOP_K = 20
SEARCH_RESULTS = 10
MIN_QUERY_LENGTH = 15    # skip search for shorter queries
MIN_RRF_SCORE = 0.015    # discard results below this threshold


# ---------------------------------------------------------------------------
# Query rewriting (P6)
# ---------------------------------------------------------------------------

_GREETING_PATTERN = re.compile(
    r"\b(hi|hello|hey|greetings|good\s+(?:morning|afternoon|evening))\b[,!.\s]*",
    re.IGNORECASE,
)

_HEDGING_PATTERN = re.compile(
    r"\b("
    r"can you|could you|would you|will you|"
    r"i was wondering if|i was wondering|"
    r"would you mind|do you think you could|"
    r"i need you to|i want you to|i'd like you to|"
    r"help me with|help me|"
    r"tell me about|tell me|"
    r"show me|explain to me|"
    r"i have a question about|"
    r"quick question"
    r")\b\s*",
    re.IGNORECASE,
)

_STOP_WORDS = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "do", "does", "did", "have", "has", "had", "having",
    "it", "its", "this", "that", "these", "those",
    "about", "just", "really", "very", "also", "actually", "basically",
    "so", "like", "well", "anyway", "right", "okay", "ok",
    "some", "any", "much", "many", "more", "most",
    "not", "no", "nor", "but", "or", "and", "if", "then",
    "of", "in", "on", "at", "to", "for", "with", "from", "by",
    "up", "out", "into", "over", "after", "before",
    "i", "me", "my", "mine", "myself",
    "you", "your", "yours", "yourself",
    "we", "our", "ours", "ourselves",
    "they", "them", "their", "theirs",
    "he", "she", "him", "her", "his", "hers",
    "there", "here",
})

# Matches technical terms: dotted names (foo.bar), hyphenated (my-thing),
# underscored (my_thing), or camelCase (myThing).
_TECHNICAL_TERM_PATTERN = re.compile(
    r"\b[a-zA-Z0-9]+[._-][a-zA-Z0-9]+(?:[._-][a-zA-Z0-9]+)*\b"  # dotted/hyphenated/underscored
    r"|\b[a-z]+[A-Z][a-zA-Z]*\b"  # camelCase
)

_QUOTED_STRING_PATTERN = re.compile(r'"[^"]+"|\'[^\']+\'')


def rewrite_query(message: str) -> str:
    """Transform a user message into a search-optimized query.

    Strips greetings, hedging phrases, and stop words. Preserves quoted
    strings, technical terms (dotted/hyphenated/underscored/camelCase),
    and content words.

    If the rewritten query is empty, falls back to the original message.
    Logs the original and rewritten queries to stderr.
    """
    # 1. Extract and preserve quoted strings and technical terms
    preserved: list[str] = []
    for match in _QUOTED_STRING_PATTERN.finditer(message):
        preserved.append(match.group())
    for match in _TECHNICAL_TERM_PATTERN.finditer(message):
        preserved.append(match.group())

    # 2. Strip greetings and hedging phrases
    text = _GREETING_PATTERN.sub(" ", message)
    text = _HEDGING_PATTERN.sub(" ", text)

    # 3. Strip trailing question marks and exclamation marks
    text = re.sub(r"[?!]+", " ", text)

    # 4. Tokenize and filter stop words
    words = re.findall(r"\w+", text)
    content_words = [w for w in words if w.lower() not in _STOP_WORDS]

    # 5. Combine preserved terms + content words, deduplicate preserving order
    all_terms = preserved + content_words
    seen: set[str] = set()
    deduped: list[str] = []
    for term in all_terms:
        lower = term.lower()
        if lower not in seen:
            seen.add(lower)
            deduped.append(term)

    rewritten = " ".join(deduped).strip()

    # 6. Fallback: if rewriting removed everything, use the original
    if not rewritten:
        rewritten = message.strip()

    # 7. Log for debugging and quality assessment
    if rewritten != message.strip():
        logger.debug('Query rewrite: "%s" -> "%s"', message.strip(), rewritten)

    return rewritten


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
        logger.error("Memory vector indexing failed: %s", e)
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
        logger.warning("Vector search skipped (Ollama down): %s", e)
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
    conn: sqlite3.Connection,
    query_text: str,
    limit: int = SEARCH_RESULTS,
    min_score: float = MIN_RRF_SCORE,
) -> list[dict[str, Any]]:
    """Hybrid search: BM25 + vector, merged with Reciprocal Rank Fusion.

    Results below min_score are discarded. Each returned result dict
    includes an ``rrf_score`` key.
    """
    bm25_results = search_bm25(conn, query_text)
    vec_results = await search_vector(conn, query_text)

    if vec_results is None:
        # Ollama down -- BM25 only, apply RRF scoring for single modality
        rrf_scores: dict[str, float] = {}
        doc_map: dict[str, dict] = {}
        for rank, doc in enumerate(bm25_results, start=1):
            key = doc["chunk_key"]
            rrf_scores[key] = 1 / (RRF_K + rank)
            doc_map[key] = doc

        # Log all scores for threshold tuning
        sorted_keys = sorted(rrf_scores, key=lambda k: rrf_scores[k], reverse=True)
        logger.debug(
            "RRF scores (BM25-only) for query=%r: %s",
            query_text,
            ", ".join(f"{k}={rrf_scores[k]:.4f}" for k in sorted_keys),
        )

        # Filter and attach scores
        results: list[dict[str, Any]] = []
        for key in sorted_keys:
            if rrf_scores[key] >= min_score and len(results) < limit:
                doc = doc_map[key]
                doc["rrf_score"] = rrf_scores[key]
                results.append(doc)
        return results

    # RRF merge: score(doc) = sum(1 / (k + rank)) across both result lists
    rrf_scores = {}
    doc_map = {}

    for rank, doc in enumerate(bm25_results, start=1):
        key = doc["chunk_key"]
        rrf_scores[key] = rrf_scores.get(key, 0) + 1 / (RRF_K + rank)
        doc_map[key] = doc

    for rank, doc in enumerate(vec_results, start=1):
        key = doc["chunk_key"]
        rrf_scores[key] = rrf_scores.get(key, 0) + 1 / (RRF_K + rank)
        doc_map[key] = doc

    # Log all scores for threshold tuning
    sorted_keys = sorted(rrf_scores, key=lambda k: rrf_scores[k], reverse=True)
    logger.debug(
        "RRF scores (hybrid) for query=%r: %s",
        query_text,
        ", ".join(f"{k}={rrf_scores[k]:.4f}" for k in sorted_keys),
    )

    # Filter by minimum score and attach rrf_score to each result
    results = []
    for key in sorted_keys:
        if rrf_scores[key] >= min_score and len(results) < limit:
            doc = doc_map[key]
            doc["rrf_score"] = rrf_scores[key]
            results.append(doc)

    return results


def format_context(
    results: list[dict[str, Any]],
    max_tokens: int = 750,
) -> str | None:
    """Format search results into a context string for the system prompt.

    Each result is prefixed with its RRF score so the agent can gauge
    relevance. Output is capped at max_tokens (estimated as chars // 4).
    """
    if not results:
        return None

    max_chars = max_tokens * 4
    parts: list[str] = []
    total = 0
    for r in results:
        score = r.get("rrf_score", 0)
        entry = f"[score: {score:.4f}] {r['content']}"
        if total + len(entry) > max_chars:
            remaining = max_chars - total
            if remaining > 100:
                parts.append(entry[:remaining] + "...")
            break
        parts.append(entry)
        total += len(entry)

    return "\n\n".join(parts) if parts else None


# ---------------------------------------------------------------------------
# Index pruning
# ---------------------------------------------------------------------------


def prune_old_index_entries(
    conn: sqlite3.Connection,
    retention_days: int = 90,
) -> int:
    """Remove index entries older than retention_days from FTS and vec.

    Does NOT delete the underlying memory files from disk -- they remain
    for archival. Facts extracted from those files survive in the
    ``facts`` table, which is independent of the search index.

    Returns the number of entries pruned.

    Note on FTS5: ``created_at`` is an UNINDEXED column. We use the same
    ``DELETE ... WHERE rowid IN (subquery)`` pattern as ``delete_memory_index``
    which already operates on this FTS5 table successfully.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    cutoff_str = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")

    # Find old entries -- collect chunk_keys before deleting
    old_entries = conn.execute(
        "SELECT chunk_key FROM memory_fts WHERE created_at < ?",
        (cutoff_str,),
    ).fetchall()

    if not old_entries:
        return 0

    chunk_keys = [r[0] for r in old_entries]

    # Delete old FTS entries using the same rowid-subquery pattern as
    # delete_memory_index (proven to work on this FTS5 table)
    conn.execute(
        "DELETE FROM memory_fts WHERE rowid IN ("
        "  SELECT rowid FROM memory_fts WHERE created_at < ?"
        ")",
        (cutoff_str,),
    )

    # Delete corresponding vec entries via mapping table
    for chunk_key in chunk_keys:
        vec_row = conn.execute(
            "SELECT vec_rowid FROM memory_vec_map WHERE chunk_key = ?",
            (chunk_key,),
        ).fetchone()
        if vec_row:
            try:
                conn.execute("DELETE FROM memory_vec WHERE rowid = ?", (vec_row[0],))
            except sqlite3.OperationalError:
                pass
            conn.execute(
                "DELETE FROM memory_vec_map WHERE chunk_key = ?",
                (chunk_key,),
            )

    conn.commit()
    return len(chunk_keys)
