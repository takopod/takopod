"""Seed and update builtin MCP server rows in the database."""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import sys
import uuid

import aiosqlite

logger = logging.getLogger(__name__)


async def _check_cli_auth(
    cli: str,
    *,
    auth_check: list[str] | None = None,
) -> str | None:
    """Check if a CLI tool is authenticated. Returns an error note or None.

    Args:
        auth_check: Custom command tokens for the auth check.  Defaults to
                    ``[cli, "auth", "status"]``.
    """
    cmd = auth_check or [cli, "auth", "status"]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(proc.communicate(), timeout=10)
        if proc.returncode != 0:
            return f"Not authenticated. Run '{cli} auth login' in your terminal."
    except Exception:
        return f"Could not verify auth status for {cli}."
    return None


async def seed_builtin_mcp_servers(db: aiosqlite.Connection) -> None:
    """Upsert builtin MCP server rows based on current integration configs.

    Called at startup and whenever integration settings are saved/deleted.
    """
    from orchestrator.slack_routes import _read_slack_config

    slack_config = _read_slack_config()
    if slack_config:
        env = {
            "_display_name": "Slack",
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

    await _seed_cli_integration(
        db,
        cli="gh",
        name="github",
        display_name="Github",
        module="integrations.github_mcp",
        install_hint="brew install gh",
    )

    await _seed_cli_integration(
        db,
        cli="gws",
        name="gws",
        display_name="Google Workspace",
        module="integrations.gws_mcp",
        install_hint="npm install -g @anthropic-ai/gws",
    )

    await _seed_cli_integration(
        db,
        cli="acli",
        name="jira",
        display_name="Jira",
        module="integrations.jira_mcp",
        install_hint="brew tap atlassian/acli && brew install acli",
        auth_check=["acli", "jira", "auth", "status"],
    )

    await db.commit()


async def _seed_cli_integration(
    db: aiosqlite.Connection,
    *,
    cli: str,
    name: str,
    display_name: str,
    module: str,
    install_hint: str,
    auth_check: list[str] | None = None,
) -> None:
    """Register a CLI-based MCP server, always -- with a status note if unavailable.

    Args:
        auth_check: Custom command tokens for the auth status check.
                    Defaults to ``[cli, "auth", "status"]``.  Pass an explicit
                    list when the CLI nests auth under a subcommand
                    (e.g. ``["acli", "jira", "auth", "status"]``).
    """
    env: dict[str, str] = {"_display_name": display_name}

    if not shutil.which(cli):
        env["_note"] = f"{cli} CLI not installed. Run: {install_hint}"
        logger.warning("%s CLI not found on host — registering with note", cli)
    else:
        auth_note = await _check_cli_auth(cli, auth_check=auth_check)
        if auth_note:
            env["_note"] = auth_note
            logger.warning("%s CLI auth issue: %s", cli, auth_note)

    await _upsert_builtin(
        db,
        name=name,
        command=sys.executable,
        args=["-m", module],
        env=env,
        timeout=360.0,
    )


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
