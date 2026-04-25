"""File-watch checker — detects new files in a watched directory."""

from __future__ import annotations

import logging
from pathlib import Path

from orchestrator.checkers import CheckResult, register
from orchestrator.db import get_db

logger = logging.getLogger(__name__)

IPC_FILES = {"input.json", "output.json", "request.json", "response.json"}


@register("file_watch")
async def check_file_watch(config: dict, cursor: dict) -> CheckResult:
    agent_id = config.get("agent_id", "")
    watch_dir = config.get("watch_dir", "")
    if not watch_dir or not agent_id:
        return CheckResult(changed=False, new_cursor=cursor, summary="")

    current = set(await _get_dir_listing(agent_id, watch_dir))
    previous = set(cursor.get("snapshot", []))
    new_files = sorted(current - previous)

    if not new_files:
        return CheckResult(changed=False, new_cursor=cursor, summary="")

    new_cursor = {"snapshot": sorted(current)}
    file_list = ", ".join(new_files)
    summary = f"New files detected: {file_list}"
    return CheckResult(changed=True, new_cursor=new_cursor, summary=summary)


async def _get_dir_listing(agent_id: str, watch_dir: str) -> list[str]:
    db = await get_db()
    async with db.execute(
        "SELECT host_dir FROM agents WHERE id = ?", (agent_id,),
    ) as cur:
        row = await cur.fetchone()
    if not row:
        return []

    host_dir = Path(row[0])
    target = host_dir / watch_dir

    try:
        target = target.resolve()
        if not target.is_relative_to(host_dir.resolve()):
            return []
    except (ValueError, OSError):
        return []

    if not target.is_dir():
        return []

    result = []
    try:
        for entry in target.iterdir():
            if entry.is_file() and entry.name not in IPC_FILES and not entry.name.endswith(".log"):
                result.append(entry.name)
    except OSError:
        pass
    return sorted(result)
