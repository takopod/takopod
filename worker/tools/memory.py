"""Memory management tools — search, store, and delete persistent facts.

Exposes search, store, and delete as MCP tools under the "memory" server
(mcp__memory__search, mcp__memory__store, mcp__memory__delete).
"""

import json
import logging
import re
import sqlite3
import time
from typing import Any

logger = logging.getLogger(__name__)

from claude_agent_sdk import create_sdk_mcp_server, tool

from worker.memory import _VALID_CATEGORIES, store_facts
from worker.search import search_hybrid

TOOL_NAMES = [
    "mcp__memory__search",
    "mcp__memory__store",
    "mcp__memory__delete",
]

_WRITE_LIMIT = 20

_write_count: int = 0

search_schema: dict[str, Any] = {
    "name": "search",
    "description": (
        "Search past conversations and stored facts. Use when you need to "
        "recall something from previous sessions not in current context, "
        "or cross-reference a different topic."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query text",
                "minLength": 3,
                "maxLength": 500,
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of results to return",
                "minimum": 1,
                "maximum": 20,
                "default": 5,
            },
            "include_facts": {
                "type": "boolean",
                "description": "Whether to include matching facts in results",
                "default": True,
            },
        },
        "required": ["query"],
    },
}

store_schema: dict[str, Any] = {
    "name": "store",
    "description": (
        "Store a fact to persistent memory. Use when the user asks you to "
        "remember something, or when you learn a key preference, decision, "
        "or entity. Facts with the same key are automatically updated."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "key": {
                "type": "string",
                "description": "Fact key (will be normalized to lowercase with underscores)",
                "maxLength": 100,
            },
            "value": {
                "type": "string",
                "description": "Fact value to store",
                "maxLength": 500,
            },
            "category": {
                "type": "string",
                "description": "Fact category",
                "enum": ["preference", "project", "decision", "entity", "config", "general"],
                "default": "general",
            },
        },
        "required": ["key", "value"],
    },
}

delete_schema: dict[str, Any] = {
    "name": "delete",
    "description": (
        "Remove a fact from active memory by marking it superseded. "
        "Use when a stored fact is no longer true or relevant."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "key": {
                "type": "string",
                "description": "Fact key to delete",
                "maxLength": 100,
            },
        },
        "required": ["key"],
    },
}


def _text_result(data: dict[str, Any]) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(data, indent=2)}]}


def create_memory_server(conn: sqlite3.Connection):
    """Build an in-process MCP server with memory management tools."""

    @tool(
        search_schema["name"],
        search_schema["description"],
        search_schema["input_schema"],
    )
    async def search(args: dict[str, Any]) -> dict[str, Any]:
        query_text = args.get("query", "")
        if len(query_text) < 3 or len(query_text) > 500:
            return _text_result({"error": "query must be 3-500 characters"})

        limit = args.get("limit", 5)
        limit = max(1, min(20, limit))
        include_facts = args.get("include_facts", True)

        try:
            results = await search_hybrid(conn, query_text, limit=limit)

            search_results = []
            for r in results:
                content = r.get("content", "")
                if len(content) > 500:
                    content = content[:500] + "..."
                search_results.append({
                    "content": content,
                    "file_path": r.get("file_path", ""),
                    "session_ref": r.get("session_ref", ""),
                    "rrf_score": round(r.get("rrf_score", 0), 4),
                })

            facts = []
            if include_facts:
                escaped = query_text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                like_param = f"%{escaped}%"
                rows = conn.execute(
                    "SELECT key, value, category FROM facts "
                    "WHERE superseded = 0 AND (key LIKE ? ESCAPE '\\' OR value LIKE ? ESCAPE '\\') "
                    "ORDER BY category, key LIMIT ?",
                    (like_param, like_param, limit),
                ).fetchall()
                facts = [{"key": r[0], "value": r[1], "category": r[2]} for r in rows]

            logger.debug(
                "search query=%r results=%d facts=%d",
                query_text, len(search_results), len(facts),
            )

            return _text_result({
                "search_results": search_results,
                "facts": facts,
                "result_count": len(search_results),
                "fact_count": len(facts),
            })

        except Exception as e:
            logger.error("search failed: %s", e)
            return _text_result({"error": f"Search failed: {e}"})

    @tool(
        store_schema["name"],
        store_schema["description"],
        store_schema["input_schema"],
    )
    async def store(args: dict[str, Any]) -> dict[str, Any]:
        global _write_count

        key = args.get("key", "")
        value = args.get("value", "")
        category = args.get("category", "general")

        if not key or len(key) > 100:
            return _text_result({"error": "key must be 1-100 characters"})
        if not value or len(value) > 500:
            return _text_result({"error": "value must be 1-500 characters"})
        if category not in _VALID_CATEGORIES:
            return _text_result({"error": f"invalid category: {category}"})

        if _write_count >= _WRITE_LIMIT:
            return _text_result({"error": "write limit reached for this session"})

        try:
            normalized_key = re.sub(r"[\s_]+", "_", key.strip().lower())

            existing = conn.execute(
                "SELECT value FROM facts WHERE key = ? AND superseded = 0",
                (normalized_key,),
            ).fetchone()
            if existing is None:
                action = "inserted"
            elif existing[0] == value:
                action = "confirmed"
            else:
                action = "updated"

            store_facts(conn, [{"key": normalized_key, "value": value, "category": category}], source="tool:explicit")
            _write_count += 1

            logger.debug(
                "store key=%r action=%s writes=%d/%d",
                normalized_key, action, _write_count, _WRITE_LIMIT,
            )

            return _text_result({
                "stored": True,
                "key": normalized_key,
                "value": value,
                "category": category,
                "action": action,
            })

        except Exception as e:
            logger.error("store failed: %s", e)
            return _text_result({"error": f"Store failed: {e}"})

    @tool(
        delete_schema["name"],
        delete_schema["description"],
        delete_schema["input_schema"],
    )
    async def delete(args: dict[str, Any]) -> dict[str, Any]:
        global _write_count

        key = args.get("key", "")
        if not key or len(key) > 100:
            return _text_result({"error": "key must be 1-100 characters"})

        if _write_count >= _WRITE_LIMIT:
            return _text_result({"error": "write limit reached for this session"})

        try:
            normalized_key = re.sub(r"[\s_]+", "_", key.strip().lower())
            now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

            cursor = conn.execute(
                "UPDATE facts SET superseded = 1, updated_at = ? "
                "WHERE key = ? AND superseded = 0",
                (now_iso, normalized_key),
            )
            conn.commit()
            _write_count += 1

            if cursor.rowcount > 0:
                logger.debug("delete key=%r writes=%d/%d", normalized_key, _write_count, _WRITE_LIMIT)
                return _text_result({"deleted": True, "key": normalized_key})

            logger.debug("delete key=%r not found writes=%d/%d", normalized_key, _write_count, _WRITE_LIMIT)
            return _text_result({"deleted": False, "key": normalized_key, "reason": "not found"})

        except Exception as e:
            logger.error("delete failed: %s", e)
            return _text_result({"error": f"Delete failed: {e}"})

    return create_sdk_mcp_server(
        name="memory",
        version="1.0.0",
        tools=[search, store, delete],
    )
