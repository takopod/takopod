"""Seed and update builtin MCP server rows in the database."""

from __future__ import annotations

import json
import logging
import shutil
import sys
import uuid

import aiosqlite

logger = logging.getLogger(__name__)


async def seed_builtin_mcp_servers(db: aiosqlite.Connection) -> None:
    """Upsert builtin MCP server rows based on current integration configs.

    Called at startup and whenever integration settings are saved/deleted.
    """
    from orchestrator.slack_routes import _read_slack_config

    slack_config = _read_slack_config()
    if slack_config:
        env = {
            "SLACK_XOXC_TOKEN": slack_config["xoxc_token"],
            "SLACK_D_COOKIE": slack_config["d_cookie"],
            "MY_MEMBER_ID": slack_config.get("member_id", ""),
        }
        await _upsert_builtin(
            db,
            name="slack",
            command=sys.executable,
            args=["-m", "integrations.slack_mcp"],
            env=env,
        )
    else:
        await _remove_builtin(db, "slack")

    if shutil.which("gh"):
        await _upsert_builtin(
            db,
            name="github",
            command=sys.executable,
            args=["-m", "integrations.github_mcp"],
            env={},
            timeout=360.0,
        )
    else:
        logger.warning("gh CLI not found on host — GitHub MCP server disabled")
        await _remove_builtin(db, "github")

    await db.commit()


async def _upsert_builtin(
    db: aiosqlite.Connection,
    *,
    name: str,
    command: str,
    args: list[str],
    env: dict[str, str],
    timeout: float = 30.0,
) -> None:
    async with db.execute(
        "SELECT id FROM mcp_servers WHERE name = ?", (name,),
    ) as cur:
        row = await cur.fetchone()

    args_json = json.dumps(args)
    env_json = json.dumps(env)

    if row:
        await db.execute(
            "UPDATE mcp_servers SET command = ?, args = ?, env = ?, timeout = ? "
            "WHERE id = ?",
            (command, args_json, env_json, timeout, row[0]),
        )
        logger.info("Updated builtin MCP server '%s'", name)
    else:
        server_id = str(uuid.uuid4())
        await db.execute(
            "INSERT INTO mcp_servers (id, name, command, args, env, timeout, builtin) "
            "VALUES (?, ?, ?, ?, ?, ?, 1)",
            (server_id, name, command, args_json, env_json, timeout),
        )
        logger.info("Created builtin MCP server '%s' (id=%s)", name, server_id)


async def _remove_builtin(db: aiosqlite.Connection, name: str) -> None:
    async with db.execute(
        "SELECT id FROM mcp_servers WHERE name = ? AND builtin = 1", (name,),
    ) as cur:
        row = await cur.fetchone()
    if row:
        # CASCADE on agent_mcp_servers handles cleanup
        await db.execute("DELETE FROM mcp_servers WHERE id = ?", (row[0],))
        logger.info("Removed builtin MCP server '%s'", name)
