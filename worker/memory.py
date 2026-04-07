"""Session memory: summarization, daily memory file I/O, and context loading."""

import asyncio
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

MEMORY_TOKEN_BUDGET = 4000
CHARS_PER_TOKEN = 4
MEMORY_CHAR_BUDGET = MEMORY_TOKEN_BUDGET * CHARS_PER_TOKEN

MAX_FILE_SIZE = 8000  # chars; triggers continuation file
MAX_SUMMARY_INPUT = 50000  # chars; truncation for summarization input
SUMMARIZE_TIMEOUT = 45  # seconds

MAX_CONTINUATION_FILES = 3  # compact when a 4th file would be created

SUMMARIZE_SYSTEM_PROMPT = (
    "You are a session summarizer. Produce a concise summary of the following "
    "conversation. Focus on:\n"
    "- What the user asked for or wanted to accomplish (their intent)\n"
    "- Decisions made and conclusions reached\n"
    "- Unresolved questions or next steps\n\n"
    "Important: Do NOT include specific tool results, search results, or "
    "intermediate findings as facts. For example, if a search returned results "
    "from a specific channel, do not record that channel as the definitive "
    "source — the search may have been incomplete. Summarize the user's intent "
    "and what was or wasn't resolved, not the raw data returned by tools.\n\n"
    "Output only the summary, no preamble."
)

COMPACT_SYSTEM_PROMPT = (
    "You are a memory compactor. The following contains multiple session summaries "
    "from the same day. Distill them into a single, coherent summary that preserves "
    "all important information: key decisions, facts learned, topics discussed, "
    "and unresolved questions. Remove redundancy. Output only the distilled summary, "
    "no preamble."
)


async def summarize_session(
    conn: sqlite3.Connection, session_id: str,
) -> str | None:
    """Summarize a session's conversation by calling Claude.

    Queries message_fts for all messages in the session, formats them as a
    transcript, and asks Claude for a summary. Returns None if the session
    has no messages or if summarization fails.
    """
    if not session_id:
        return None

    rows = conn.execute(
        "SELECT role, content FROM message_fts "
        "WHERE session_id = ? ORDER BY rowid",
        (session_id,),
    ).fetchall()

    if not rows:
        sys.stderr.write("memory: no messages to summarize\n")
        sys.stderr.flush()
        return None

    # Format as transcript
    transcript_parts: list[str] = []
    for role, content in rows:
        transcript_parts.append(f"[{role}]: {content}")
    transcript = "\n\n".join(transcript_parts)

    if len(transcript) > MAX_SUMMARY_INPUT:
        transcript = transcript[:MAX_SUMMARY_INPUT] + "\n\n[...truncated]"

    sys.stderr.write(
        f"memory: summarizing session {session_id} "
        f"({len(rows)} messages, {len(transcript)} chars)\n"
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

    # Delete continuation files
    for rel_path in paths:
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

        sys.stderr.write(f"memory: wrote summary to {rel_path}\n")
        sys.stderr.flush()
        return rel_path, needs_compaction

    except Exception as e:
        sys.stderr.write(f"memory: failed to write memory file: {e}\n")
        sys.stderr.flush()
        return None, False


def load_memory_context(conn: sqlite3.Connection) -> str | None:
    """Load MEMORY.md and recent daily memory files for context injection.

    Returns assembled memory context string, or None if nothing to load.
    Memory files are loaded most-recent-first until the character budget
    (MEMORY_CHAR_BUDGET) is exhausted.
    """
    parts: list[str] = []

    # Always include MEMORY.md in full
    memory_md_content = None
    if MEMORY_MD.is_file():
        text = MEMORY_MD.read_text().strip()
        if text:
            memory_md_content = text

    if memory_md_content:
        parts.append(f"## Persistent Memory\n\n{memory_md_content}")

    # Load daily memory files (most recent first)
    rows = conn.execute(
        "SELECT file_path FROM memory_files ORDER BY date DESC, file_path DESC",
    ).fetchall()

    if rows:
        budget = MEMORY_CHAR_BUDGET
        daily_parts: list[str] = []

        for (rel_path,) in rows:
            if budget <= 0:
                break
            abs_path = WORKSPACE / rel_path
            if not abs_path.is_file():
                continue
            content = abs_path.read_text().strip()
            if not content:
                continue
            if len(content) > budget:
                content = content[:budget] + "\n\n[...truncated]"
                budget = 0
            else:
                budget -= len(content)
            daily_parts.append(content)

        if daily_parts:
            parts.append(
                "## Session History\n\n"
                + "\n\n".join(daily_parts)
            )

    if not parts:
        return None

    return "\n\n".join(parts)


async def run_session_end(
    conn: sqlite3.Connection,
    session_id: str | None,
    sdk_session_id: str | None,
) -> str | None:
    """Run session-end memory operations: summarize and write memory file.

    Called on shutdown and clear_context. Returns the date string that needs
    compaction, or None if no compaction is needed. The caller is responsible
    for scheduling compaction (e.g., emitting a schedule_compaction event).
    Failures are non-fatal.
    """
    if not session_id:
        sys.stderr.write("memory: no session_id, skipping session-end summary\n")
        sys.stderr.flush()
        return None

    summary = await summarize_session(conn, session_id)
    if not summary:
        sys.stderr.write("memory: no summary produced, skipping memory write\n")
        sys.stderr.flush()
        return None

    # Derive session filepath from SDK session ID
    if sdk_session_id:
        session_filepath = f"sessions/{sdk_session_id}.jsonl"
    else:
        session_filepath = f"sessions/unknown-{session_id[:8]}"

    _path, needs_compaction = write_memory_file(conn, summary, session_filepath)

    if needs_compaction:
        today = time.strftime("%Y-%m-%d", time.gmtime())
        sys.stderr.write(
            f"memory: compaction needed for {today}\n"
        )
        sys.stderr.flush()
        return today

    return None
