"""Session memory: summarization, daily memory file I/O, and context loading."""

import asyncio
import json
import re
import sqlite3
import sys
import time
import uuid
from pathlib import Path
from typing import Any

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
    "You are a session summarizer. Produce a summary of the following "
    "conversation in two sections.\n\n"
    "## Facts\n"
    "Extract key facts as a JSON array. Each fact is an object with three fields:\n"
    '- "key": snake_case identifier (e.g., "user_name", "project_framework")\n'
    '- "value": the fact value as a string\n'
    '- "category": one of "preference", "project", "decision", "entity", "config", "general"\n\n'
    "Example:\n"
    '```json\n'
    '[{"key": "user_name", "value": "Shaon", "category": "preference"},\n'
    ' {"key": "project_framework", "value": "FastAPI + React", "category": "project"}]\n'
    '```\n\n'
    "Only include facts that are explicitly stated or clearly implied. "
    "Do not speculate. If no facts are extractable, output an empty array `[]`.\n\n"
    "## Summary\n"
    "A concise narrative summary focusing on:\n"
    "- What the user asked for or wanted to accomplish\n"
    "- Decisions made and conclusions reached\n"
    "- Unresolved questions or next steps\n\n"
    "Important: Do NOT include specific tool results, search results, or "
    "intermediate findings as facts. For example, if a search returned results "
    "from a specific channel, do not record that channel as the definitive "
    "source -- the search may have been incomplete. Summarize the user's intent "
    "and what was or wasn't resolved, not the raw data returned by tools.\n\n"
    "Output only the two sections, no preamble."
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
        sys.stderr.write("memory: no JSON facts array found in output\n")
        sys.stderr.flush()
        return []

    # Strip trailing commas before closing bracket (common LLM formatting error)
    json_str = re.sub(r",\s*\]", "]", json_str)

    try:
        parsed = json.loads(json_str)
    except json.JSONDecodeError as e:
        sys.stderr.write(f"memory: facts JSON parse failed: {e}\n")
        sys.stderr.flush()
        return []

    if not isinstance(parsed, list):
        sys.stderr.write(
            f"memory: facts JSON is not an array: {type(parsed).__name__}\n"
        )
        sys.stderr.flush()
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

    sys.stderr.write(f"memory: parsed {len(facts)} facts from JSON\n")
    sys.stderr.flush()
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
    sys.stderr.write(
        f"memory: stored {written} facts (source={source})\n"
    )
    sys.stderr.flush()
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
        sys.stderr.write(
            f"memory: facts table already has {count} rows, skipping markdown migration\n"
        )
        sys.stderr.flush()
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
        sys.stderr.write("memory: no markdown facts found to migrate\n")
        sys.stderr.flush()
        return 0

    # Insert all facts with source=migration:markdown
    migrated_facts = [
        {"key": norm_key, "value": value, "category": "general"}
        for norm_key, (_orig_key, value) in facts.items()
    ]
    written = store_facts(conn, migrated_facts, source="migration:markdown")

    sys.stderr.write(f"memory: migrated {written} facts from markdown to DB\n")
    sys.stderr.flush()
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
    "from the same day. Distill them into a single coherent document with two sections.\n\n"
    "## Facts\n"
    "Merge all facts from the sessions into a single JSON array. Deduplicate by key "
    "(keep the value from the latest session if keys conflict). Each fact is an object:\n"
    '- "key": snake_case identifier\n'
    '- "value": the fact value as a string\n'
    '- "category": one of "preference", "project", "decision", "entity", "config", "general"\n\n'
    "If there are no facts in any session, output an empty array `[]`.\n\n"
    "## Summary\n"
    "A single narrative summary preserving key decisions, topics discussed, "
    "and unresolved questions. Remove redundancy.\n\n"
    "Output only the two sections, no preamble."
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
        sys.stderr.write("memory: no messages to summarize\n")
        sys.stderr.flush()
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

    sys.stderr.write(
        f"memory: summarizing session "
        f"({len(transcript_turns)} messages, {len(transcript)} chars)\n"
    )
    sys.stderr.flush()

    try:
        summary = await asyncio.wait_for(
            _call_summarize(transcript), timeout=SUMMARIZE_TIMEOUT,
        )
        return summary
    except asyncio.TimeoutError:
        sys.stderr.write("memory: summarization timed out\n")
        sys.stderr.flush()
        return None
    except Exception as e:
        sys.stderr.write(f"memory: summarization failed: {e}\n")
        sys.stderr.flush()
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

    sys.stderr.write(f"memory: summary generated ({len(summary)} chars)\n")
    sys.stderr.flush()
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

    sys.stderr.write(
        f"memory: compacting {len(paths)} files for {date} "
        f"({len(combined)} chars)\n"
    )
    sys.stderr.flush()

    try:
        distilled = await asyncio.wait_for(
            _call_compact(combined), timeout=SUMMARIZE_TIMEOUT,
        )
    except asyncio.TimeoutError:
        sys.stderr.write("memory: compaction timed out\n")
        sys.stderr.flush()
        return None
    except Exception as e:
        sys.stderr.write(f"memory: compaction failed: {e}\n")
        sys.stderr.flush()
        return None

    if not distilled:
        return None

    # Write the single compacted file
    canonical_path = f"memory/{date}.md"
    abs_canonical = WORKSPACE / canonical_path
    abs_canonical.write_text(f"## Compacted Memory — {date}\n\n{distilled}\n")

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

    # Index the compacted file
    compacted_content = abs_canonical.read_text()
    index_memory_file(conn, canonical_path, compacted_content)
    await index_memory_vectors(conn, canonical_path, compacted_content)

    # Extract and store facts from the compacted output into the DB
    try:
        parsed_facts = parse_facts_json(distilled)
        if parsed_facts:
            store_facts(conn, parsed_facts, source=f"compaction:{date}")
    except Exception as e:
        sys.stderr.write(f"memory: fact storage after compaction failed: {e}\n")
        sys.stderr.flush()

    sys.stderr.write(
        f"memory: compacted {len(paths)} files into {canonical_path} "
        f"({len(distilled)} chars)\n"
    )
    sys.stderr.flush()
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

    # Format the entry
    entry = f"## Session: {session_filepath}\n\n{summary}\n\n---\n"
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

        # Write or append
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

        # Index into memory_fts for search retrieval
        from worker.search import index_memory_file
        file_content = abs_path.read_text()
        index_memory_file(conn, rel_path, file_content)

        # Extract and store facts from the summary into the DB
        try:
            parsed_facts = parse_facts_json(summary)
            if parsed_facts:
                session_ref = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
                store_facts(conn, parsed_facts, source=f"session:{session_ref}")
        except Exception as e:
            sys.stderr.write(f"memory: fact storage after write failed: {e}\n")
            sys.stderr.flush()

        sys.stderr.write(f"memory: wrote summary to {rel_path}\n")
        sys.stderr.flush()
        return rel_path, needs_compaction

    except Exception as e:
        sys.stderr.write(f"memory: failed to write memory file: {e}\n")
        sys.stderr.flush()
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
        sys.stderr.write("memory: no transcript, skipping session-end summary\n")
        sys.stderr.flush()
        return None

    summary = await summarize_session(transcript)
    if not summary:
        sys.stderr.write("memory: no summary produced, skipping memory write\n")
        sys.stderr.flush()
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
        sys.stderr.write(
            f"memory: compaction needed for {today}\n"
        )
        sys.stderr.flush()
        return today

    return None
