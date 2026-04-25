"""Session memory: summarization, daily memory file I/O, and context loading."""

import asyncio
import json
import logging
import re
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
    query,
)

WORKSPACE = Path("/workspace")
MEMORY_DIR = WORKSPACE / "memory"
MEMORY_MD = WORKSPACE / "MEMORY.md"

MAX_FILE_SIZE = 8000  # chars; triggers continuation file
MAX_SUMMARY_INPUT = 50000  # chars; truncation for summarization input
SUMMARIZE_TIMEOUT = 45  # seconds

MAX_CONTINUATION_FILES = 3  # compact when a 4th file would be created

SUMMARIZE_SYSTEM_PROMPT = (
    "You are a session summarizer. Produce a concise narrative summary of the "
    "following conversation.\n\n"
    "Focus on:\n"
    "- What the user asked for or wanted to accomplish\n"
    "- Decisions made and conclusions reached\n"
    "- Key entities, preferences, and facts mentioned\n"
    "- Unresolved questions or next steps\n\n"
    "Only include facts that are explicitly stated or clearly implied. "
    "Do not speculate.\n\n"
    "Important: Do NOT include specific tool results, search results, or "
    "intermediate findings as facts. For example, if a search returned results "
    "from a specific channel, do not record that channel as the definitive "
    "source -- the search may have been incomplete. Summarize the user's intent "
    "and what was or wasn't resolved, not the raw data returned by tools.\n\n"
    "Output only the summary, no preamble, no JSON blocks."
)

def _normalize_fact_key(key: str) -> str:
    """Normalize a fact key: lowercase, collapse whitespace/underscores."""
    return re.sub(r"[\s_]+", "_", key.strip().lower())


# ---------------------------------------------------------------------------
# Structured fact storage (P7) — JSON-based extraction and DB persistence
# ---------------------------------------------------------------------------

_JSON_BLOCK_PATTERN = re.compile(
    r"```(?:json)?\s*\n?(.*?)\n?\s*```",  # fenced code block
    re.DOTALL,
)
_JSON_ARRAY_PATTERN = re.compile(
    r"\[\s*\]|\[\s*\{.*?\}\s*\]",  # empty array or array of objects only
    re.DOTALL,
)

_VALID_CATEGORIES = frozenset({
    "preference", "project", "decision", "entity", "config", "general",
})

# ---------------------------------------------------------------------------
# Facts block stripping — safety net for memory file writes
# ---------------------------------------------------------------------------

_FACTS_BLOCK_PATTERN = re.compile(
    r"## Facts\s*\n+"          # header
    r"```(?:json)?\s*\n"      # opening fence
    r".*?"                     # JSON content
    r"\n\s*```"                # closing fence
    r"\s*\n*",                 # trailing whitespace
    re.DOTALL,
)

_FACTS_BARE_PATTERN = re.compile(
    r"## Facts\s*\n+"          # header
    r".*?"                     # non-fenced content
    r"(?=\n## |\Z)",           # up to next ## header or end of string
    re.DOTALL,
)


def _strip_facts_block(text: str) -> str:
    """Remove ## Facts + fenced JSON block from summary text.

    Tries the fenced code block pattern first (matches existing memory file
    format). Falls back to a bare header pattern that strips everything from
    ``## Facts`` to the next ``##`` header or end of string.
    """
    result = _FACTS_BLOCK_PATTERN.sub("", text)
    if result == text:
        # Fenced pattern did not match — try bare header fallback
        result = _FACTS_BARE_PATTERN.sub("", text)
    if result != text:
        return result.strip()
    return text


def parse_facts_json(text: str) -> list[dict]:
    """Extract a JSON facts array from Claude's summarization output.

    Tries multiple extraction strategies in order:
    1. Fenced code block (```json ... ```)
    2. Bare JSON array ([{...}] or [])

    Each extracted fact must have 'key' and 'value' fields. The 'category'
    field defaults to 'general' if missing or unrecognized.

    Returns an empty list on parse failure (never raises).
    """
    json_str: str | None = None

    # Strategy 1: fenced code block
    match = _JSON_BLOCK_PATTERN.search(text)
    if match:
        json_str = match.group(1).strip()

    # Strategy 2: bare JSON array (objects only, or empty)
    if json_str is None:
        match = _JSON_ARRAY_PATTERN.search(text)
        if match:
            json_str = match.group(0).strip()

    if not json_str:
        logger.warning("No JSON facts array found in output")
        return []

    # Strip trailing commas before closing bracket (common LLM formatting error)
    json_str = re.sub(r",\s*\]", "]", json_str)

    try:
        parsed = json.loads(json_str)
    except json.JSONDecodeError as e:
        logger.error("Facts JSON parse failed: %s", e)
        return []

    if not isinstance(parsed, list):
        logger.error("Facts JSON is not an array: %s", type(parsed).__name__)
        return []

    # Validate and normalize each fact
    facts: list[dict] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        key = item.get("key")
        value = item.get("value")
        if not key or not value:
            continue
        category = item.get("category", "general")
        if category not in _VALID_CATEGORIES:
            category = "general"
        facts.append({
            "key": _normalize_fact_key(str(key)),
            "value": str(value),
            "category": category,
        })

    logger.info("Parsed %d facts from JSON", len(facts))
    return facts


def store_facts(
    conn: sqlite3.Connection,
    facts: list[dict],
    source: str,
) -> int:
    """Insert or update facts in the database with supersession handling.

    For each fact:
    - If an active row with the same normalized key exists and has the
      same value, update its updated_at timestamp (confirmation).
    - If an active row with the same key exists but has a different value,
      mark it as superseded and insert a new active row.
    - If no active row with the key exists, insert a new active row.

    Returns the number of facts written (inserted or confirmed).
    """
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    written = 0

    for fact in facts:
        key = fact["key"]
        value = fact["value"]
        category = fact.get("category", "general")

        # Check for existing active fact with same key
        existing = conn.execute(
            "SELECT id, value FROM facts WHERE key = ? AND superseded = 0",
            (key,),
        ).fetchone()

        if existing:
            existing_id, existing_value = existing
            if existing_value == value:
                # Same value -- confirm by updating timestamp
                conn.execute(
                    "UPDATE facts SET updated_at = ? WHERE id = ?",
                    (now, existing_id),
                )
            else:
                # Different value -- supersede old, insert new
                conn.execute(
                    "UPDATE facts SET superseded = 1, updated_at = ? WHERE id = ?",
                    (now, existing_id),
                )
                conn.execute(
                    "INSERT INTO facts (id, key, value, category, source, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (str(uuid.uuid4()), key, value, category, source, now, now),
                )
        else:
            # No existing active fact -- insert new
            conn.execute(
                "INSERT INTO facts (id, key, value, category, source, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), key, value, category, source, now, now),
            )

        written += 1

    conn.commit()
    logger.info("Stored %d facts (source=%s)", written, source)
    return written


def get_facts_context(conn: sqlite3.Connection) -> str | None:
    """Query active facts and format them for system prompt injection.

    Returns a formatted string with facts grouped by category, or None
    if no active facts exist. Each fact line includes the category tag.

    This replaces the old cache-based get_facts_context() which took no
    arguments. The signature change is intentional -- all callers must
    pass the DB connection.
    """
    rows = conn.execute(
        "SELECT key, value, category FROM facts "
        "WHERE superseded = 0 ORDER BY category, key",
    ).fetchall()

    if not rows:
        return None

    lines = [f"- {row[0]}: {row[1]} [{row[2]}]" for row in rows]
    return "## Known Facts\n\n" + "\n".join(lines)


# ---------------------------------------------------------------------------
# Migration-only code: markdown fact parsing
#
# These patterns and functions are used ONLY by migrate_markdown_facts_to_db()
# to import existing markdown-embedded facts into the facts table. They can
# be removed after one release cycle once all agents have been migrated.
# ---------------------------------------------------------------------------

_FACTS_HEADER_PATTERN = re.compile(
    r"^#{1,3}\s+Facts\s*$", re.MULTILINE
)
_FACT_LINE_PATTERN = re.compile(
    r"^[-*]\s*(.+?)\s*[:=]\s*(.+)$", re.MULTILINE
)


def _extract_facts_section(content: str) -> str | None:
    """Extract the Facts section body from a memory file's content.

    Matches headers with 1-3 '#' characters followed by 'Facts'.
    Returns the text between the Facts header and the next header (or EOF).

    Migration-only: used by migrate_markdown_facts_to_db().
    """
    match = _FACTS_HEADER_PATTERN.search(content)
    if not match:
        return None

    start = match.end()
    # Find the next markdown header (any level)
    next_header = re.search(r"^#{1,6}\s+", content[start:], re.MULTILINE)
    if next_header:
        section = content[start:start + next_header.start()]
    else:
        section = content[start:]

    return section.strip() or None


def _parse_fact_lines(section: str) -> list[tuple[str, str, str]]:
    """Parse fact lines from a Facts section body.

    Returns list of (original_key, value, normalized_key) tuples.
    Accepts '- key: value', '- key = value', '* key: value' formats.

    Migration-only: used by migrate_markdown_facts_to_db().
    """
    facts: list[tuple[str, str, str]] = []
    for match in _FACT_LINE_PATTERN.finditer(section):
        orig_key = match.group(1).strip()
        value = match.group(2).strip()
        norm_key = _normalize_fact_key(orig_key)
        facts.append((orig_key, value, norm_key))
    return facts


def migrate_markdown_facts_to_db(conn: sqlite3.Connection) -> int:
    """One-time migration: import existing markdown-embedded facts into the facts table.

    Reads all memory files, parses their Facts sections using the existing
    lenient regex patterns, and inserts them into the facts table.

    Idempotent: if the facts table already has rows, this is a no-op.
    Returns the number of facts migrated.
    """
    # Check if already migrated
    count = conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
    if count > 0:
        logger.info("Facts table already has %d rows, skipping markdown migration", count)
        return 0

    # Parse facts from all memory files
    facts: dict[str, tuple[str, str]] = {}

    if MEMORY_MD.is_file():
        content = MEMORY_MD.read_text()
        section = _extract_facts_section(content)
        if section:
            for orig_key, value, norm_key in _parse_fact_lines(section):
                facts[norm_key] = (orig_key, value)

    if MEMORY_DIR.is_dir():
        for md_file in sorted(MEMORY_DIR.glob("*.md")):
            content = md_file.read_text()
            section = _extract_facts_section(content)
            if section:
                for orig_key, value, norm_key in _parse_fact_lines(section):
                    facts[norm_key] = (orig_key, value)

    if not facts:
        logger.info("No markdown facts found to migrate")
        return 0

    # Insert all facts with source=migration:markdown
    migrated_facts = [
        {"key": norm_key, "value": value, "category": "general"}
        for norm_key, (_orig_key, value) in facts.items()
    ]
    written = store_facts(conn, migrated_facts, source="migration:markdown")

    logger.info("Migrated %d facts from markdown to DB", written)
    return written


_RETRIEVED_CONTEXT_PATTERN = re.compile(
    r"## Relevant Past Conversations\n+"
    r"The following excerpts are from previous conversations and may be relevant:\n+"
    r".*?(?=\n## |\Z)",
    re.DOTALL,
)


def strip_retrieved_context(text: str) -> str:
    """Remove the injected 'Relevant Past Conversations' block from text.

    The agent system prompt injects a retrieval block with this header.
    Stripping it before summarization prevents echo accumulation — where
    Day N's summary re-summarizes Day N-1's retrieved context, causing
    content to snowball across days.
    """
    return _RETRIEVED_CONTEXT_PATTERN.sub("", text).strip()


COMPACT_SYSTEM_PROMPT = (
    "You are a memory compactor. The following contains multiple session summaries "
    "from the same day. Distill them into a single coherent narrative summary.\n\n"
    "Preserve key decisions, topics discussed, entities mentioned, and "
    "unresolved questions. Remove redundancy.\n\n"
    "Output only the summary, no preamble, no JSON blocks."
)


async def summarize_session(
    transcript_turns: list[tuple[str, str]],
) -> str | None:
    """Summarize a session's conversation by calling Claude.

    Takes a list of (role, content) tuples representing the conversation
    transcript.  Returns None if the transcript is empty or summarization
    fails.
    """
    if not transcript_turns:
        logger.info("No messages to summarize")
        return None

    # Format as transcript, stripping any injected retrieval blocks
    transcript_parts: list[str] = []
    for role, content in transcript_turns:
        cleaned = strip_retrieved_context(content)
        if cleaned:
            transcript_parts.append(f"[{role}]: {cleaned}")
    transcript = "\n\n".join(transcript_parts)

    if len(transcript) > MAX_SUMMARY_INPUT:
        transcript = transcript[:MAX_SUMMARY_INPUT] + "\n\n[...truncated]"

    logger.debug(
        "Summarizing session (%d messages, %d chars)",
        len(transcript_turns), len(transcript),
    )

    try:
        summary = await asyncio.wait_for(
            _call_summarize(transcript), timeout=SUMMARIZE_TIMEOUT,
        )
        return summary
    except asyncio.TimeoutError:
        logger.warning("Summarization timed out")
        return None
    except Exception as e:
        logger.error("Summarization failed: %s", e)
        return None


async def _call_summarize(transcript: str) -> str | None:
    """Call Claude Agent SDK to produce a session summary."""
    options = ClaudeAgentOptions(
        cwd=str(WORKSPACE),
        system_prompt=SUMMARIZE_SYSTEM_PROMPT,
        max_turns=1,
        allowed_tools=[],
        permission_mode="acceptEdits",
    )

    text_parts: list[str] = []
    async for msg in query(prompt=transcript, options=options):
        if isinstance(msg, AssistantMessage):
            for block in msg.content:
                if isinstance(block, TextBlock):
                    text_parts.append(block.text)
        elif isinstance(msg, ResultMessage):
            break

    summary = "\n\n".join(text_parts).strip()
    if not summary:
        return None

    logger.info("Summary generated (%d chars)", len(summary))
    return summary


async def compact_memory_files(
    conn: sqlite3.Connection, date: str,
) -> str | None:
    """Compact all memory files for a date into a single distilled file.

    Reads all continuation files for the given date, calls Claude to distill
    them, replaces all files with a single memory/<date>.md, and updates the
    memory_files table. Returns the resulting file path, or None on failure.
    """
    rows = conn.execute(
        "SELECT file_path FROM memory_files "
        "WHERE date = ? ORDER BY file_path",
        (date,),
    ).fetchall()
    paths = [r[0] for r in rows]

    if len(paths) < 2:
        return None

    # Read all file contents
    combined_parts: list[str] = []
    for rel_path in paths:
        abs_path = WORKSPACE / rel_path
        if abs_path.is_file():
            combined_parts.append(abs_path.read_text().strip())
    combined = "\n\n---\n\n".join(combined_parts)

    if not combined.strip():
        return None

    if len(combined) > MAX_SUMMARY_INPUT:
        combined = combined[:MAX_SUMMARY_INPUT] + "\n\n[...truncated]"

    logger.info("Compacting %d files for %s (%d chars)", len(paths), date, len(combined))

    try:
        distilled = await asyncio.wait_for(
            _call_compact(combined), timeout=SUMMARIZE_TIMEOUT,
        )
    except asyncio.TimeoutError:
        logger.warning("Compaction timed out")
        return None
    except Exception as e:
        logger.error("Compaction failed: %s", e)
        return None

    if not distilled:
        return None

    # 1. Extract facts from the RAW distilled output (before stripping).
    #    Note: store_facts() calls conn.commit() internally, so facts are
    #    committed before the file write below. This is acceptable -- facts
    #    are content-correct regardless of file write success.
    try:
        parsed_facts = parse_facts_json(distilled)
        if parsed_facts:
            store_facts(conn, parsed_facts, source=f"compaction:{date}")
    except Exception as e:
        logger.error("Fact storage after compaction failed: %s", e)

    # 2. Strip facts block from distilled output before writing to disk
    clean_distilled = _strip_facts_block(distilled)
    if len(clean_distilled) < len(distilled):
        logger.debug(
            "Stripped %d chars of facts JSON", len(distilled) - len(clean_distilled),
        )

    # 3. Write clean content to disk
    canonical_path = f"memory/{date}.md"
    abs_canonical = WORKSPACE / canonical_path
    abs_canonical.write_text(f"## Compacted Memory — {date}\n\n{clean_distilled}\n")

    # Delete continuation files and their search indexes
    from worker.search import delete_memory_index, index_memory_file, index_memory_vectors
    for rel_path in paths:
        delete_memory_index(conn, rel_path)
        if rel_path != canonical_path:
            abs_path = WORKSPACE / rel_path
            if abs_path.is_file():
                abs_path.unlink()

    # Update DB: delete old rows, upsert canonical
    conn.execute("DELETE FROM memory_files WHERE date = ?", (date,))
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    file_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO memory_files (id, date, file_path, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (file_id, date, canonical_path, now, now),
    )
    conn.commit()

    # 4. Index the clean content (no facts JSON in FTS/vec)
    compacted_content = abs_canonical.read_text()
    index_memory_file(conn, canonical_path, compacted_content)
    await index_memory_vectors(conn, canonical_path, compacted_content)

    logger.info(
        "Compacted %d files into %s (%d chars)", len(paths), canonical_path, len(clean_distilled),
    )
    return canonical_path


async def _call_compact(content: str) -> str | None:
    """Call Claude Agent SDK to produce a compacted memory summary."""
    options = ClaudeAgentOptions(
        cwd=str(WORKSPACE),
        system_prompt=COMPACT_SYSTEM_PROMPT,
        max_turns=1,
        allowed_tools=[],
        permission_mode="acceptEdits",
    )

    text_parts: list[str] = []
    async for msg in query(prompt=content, options=options):
        if isinstance(msg, AssistantMessage):
            for block in msg.content:
                if isinstance(block, TextBlock):
                    text_parts.append(block.text)
        elif isinstance(msg, ResultMessage):
            break

    result = "\n\n".join(text_parts).strip()
    return result if result else None


def write_memory_file(
    conn: sqlite3.Connection, summary: str, session_filepath: str,
) -> tuple[str | None, bool]:
    """Append a session summary to the daily memory file.

    Creates continuation files (-2.md, -3.md) if the current file exceeds
    MAX_FILE_SIZE. When a file beyond MAX_CONTINUATION_FILES would be created,
    the write still proceeds but the caller is signalled to compact.

    Returns (file_path, needs_compaction). file_path is None on failure.
    After writing, the file is indexed into memory_fts for search.
    The caller should also call index_memory_vectors() for vector indexing.
    """
    today = time.strftime("%Y-%m-%d", time.gmtime())

    # 1. Extract facts from the RAW summary (before stripping)
    try:
        parsed_facts = parse_facts_json(summary)
        if parsed_facts:
            session_ref = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
            store_facts(conn, parsed_facts, source=f"session:{session_ref}")
    except Exception as e:
        logger.error("Fact storage after write failed: %s", e)

    # 2. Strip facts block from summary before writing to disk
    clean_summary = _strip_facts_block(summary)
    if len(clean_summary) < len(summary):
        logger.debug("Stripped %d chars of facts JSON", len(summary) - len(clean_summary))

    # Format the entry with clean (facts-free) summary
    entry = f"## Session: {session_filepath}\n\n{clean_summary}\n\n---\n"
    needs_compaction = False

    try:
        MEMORY_DIR.mkdir(parents=True, exist_ok=True)

        # Find existing files for today
        rows = conn.execute(
            "SELECT file_path FROM memory_files "
            "WHERE date = ? ORDER BY file_path",
            (today,),
        ).fetchall()
        existing_paths = [r[0] for r in rows]

        if not existing_paths:
            # First file for today
            rel_path = f"memory/{today}.md"
        else:
            # Check size of the latest file
            latest_rel = existing_paths[-1]
            latest_abs = WORKSPACE / latest_rel
            if latest_abs.is_file() and len(latest_abs.read_text()) + len(entry) > MAX_FILE_SIZE:
                # Would create a new continuation file
                seq = len(existing_paths) + 1
                rel_path = f"memory/{today}-{seq}.md"
                # Signal compaction if this exceeds the limit
                if seq > MAX_CONTINUATION_FILES:
                    needs_compaction = True
            else:
                # Append to latest
                rel_path = latest_rel

        abs_path = WORKSPACE / rel_path

        # 3. Write clean summary to disk
        if abs_path.is_file():
            with open(abs_path, "a") as f:
                f.write("\n" + entry)
        else:
            abs_path.write_text(entry)

        # Upsert memory_files table
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        file_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO memory_files (id, date, file_path, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(file_path) DO UPDATE SET updated_at = ?",
            (file_id, today, rel_path, now, now, now),
        )
        conn.commit()

        # 4. Index the clean content (no facts JSON in FTS/vec)
        from worker.search import index_memory_file
        file_content = abs_path.read_text()
        index_memory_file(conn, rel_path, file_content)

        logger.info("Wrote summary to %s", rel_path)
        return rel_path, needs_compaction

    except Exception as e:
        logger.error("Failed to write memory file: %s", e)
        return None, False


def load_memory_context() -> str | None:
    """Load MEMORY.md for persistent identity context injection.

    Daily memory files are no longer loaded here — they are surfaced
    via search_hybrid() which returns only relevant chunks, avoiding
    duplication with the "Relevant Past Conversations" section.
    """
    if MEMORY_MD.is_file():
        text = MEMORY_MD.read_text().strip()
        if text:
            return f"## Persistent Memory\n\n{text}"

    return None


async def run_session_end(
    conn: sqlite3.Connection,
    transcript: list[tuple[str, str]],
) -> str | None:
    """Run session-end memory operations: summarize and write memory file.

    Called on shutdown and clear_context. Takes the in-memory transcript
    (list of (role, content) tuples) for summarization.
    Returns the date string that needs compaction, or None if no compaction
    is needed. The caller is responsible for scheduling compaction.
    Failures are non-fatal.
    """
    if not transcript:
        logger.info("No transcript, skipping session-end summary")
        return None

    summary = await summarize_session(transcript)
    if not summary:
        logger.warning("No summary produced, skipping memory write")
        return None

    session_ref = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
    _path, needs_compaction = write_memory_file(conn, summary, session_ref)

    # Trigger async vector indexing for the written file
    if _path:
        from worker.search import index_memory_vectors
        file_content = (WORKSPACE / _path).read_text()
        await index_memory_vectors(conn, _path, file_content)

    if needs_compaction:
        today = time.strftime("%Y-%m-%d", time.gmtime())
        logger.info("Compaction needed for %s", today)
        return today

    return None
