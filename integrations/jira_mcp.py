"""Jira MCP server for takopod.

Exposes a ``jira`` tool that runs Atlassian CLI Jira commands on the host.

Permission enforcement (allowed / needs-approval / denied) lives in the
orchestrator, not here -- this server executes whatever it receives.

Requires the ``acli`` CLI to be installed and authenticated on the host
(``acli jira auth login``).

Usage (standalone testing):
    python -m integrations.jira_mcp
"""

from __future__ import annotations

import asyncio
import shlex

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("JiraIntegration")

SUBPROCESS_TIMEOUT = 300  # seconds
MAX_OUTPUT_BYTES = 100_000  # ~100KB


@mcp.tool()
async def jira(command: str) -> str:
    """Run a Jira CLI command. Do NOT include the leading "acli jira" prefix.

    PERMISSION TIERS -- commands are classified by their first tokens:

    Auto-approved (run immediately):
      workitem search/view, sprint view/list-workitems,
      board get/search/list-projects/list-sprints,
      project list/view, filter get/get-columns/list/search,
      dashboard search,
      workitem comment list/visibility,
      workitem link list/type,
      workitem attachment list,
      workitem watcher list

    Requires user approval (the user sees Accept/Deny buttons in chat):
      workitem create/edit/assign/transition/clone/create-bulk,
      workitem comment create/update/delete,
      workitem link create/delete,
      workitem attachment delete,
      workitem watcher remove,
      sprint create/update/delete,
      board create/delete,
      project create/update,
      filter add-favourite/change-owner/update/reset-columns,
      field create/cancel-delete

    Denied (blocked, will return an error):
      workitem delete/archive/unarchive,
      project delete/archive/restore,
      field delete,
      auth (all subcommands -- login/logout/status/switch),
      and any unrecognized commands.

    OUTPUT SIZE -- use --output-format json and --limit to keep output concise.
    Output over 100KB is truncated.

    Args:
        command: The Jira subcommand and arguments (without the "acli jira" prefix).
    """
    try:
        tokens = shlex.split(command)
    except ValueError as exc:
        return f"Error: invalid command syntax: {exc}"

    if not tokens:
        return "Error: empty command"

    proc = await asyncio.create_subprocess_exec(
        "acli", "jira", *tokens,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=SUBPROCESS_TIMEOUT,
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return f"Error: command timed out after {SUBPROCESS_TIMEOUT} seconds"

    if proc.returncode != 0:
        return f"Error (exit {proc.returncode}):\n{stderr.decode()}"

    output = stdout.decode()
    if len(stdout) > MAX_OUTPUT_BYTES:
        truncated = stdout[:MAX_OUTPUT_BYTES].decode(errors="replace")
        total_kb = len(stdout) / 1024
        return (
            f"{truncated}\n\n"
            f"--- Output truncated ({total_kb:.0f}KB total). "
            f"Use --limit or --output-format json with fewer fields to reduce output size. ---"
        )
    return output


if __name__ == "__main__":
    mcp.run()
