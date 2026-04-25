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

from mcp.server.fastmcp import FastMCP

from integrations.cli_base import run_cli_tool

mcp = FastMCP("JiraIntegration")


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
    return await run_cli_tool(
        command,
        cli_prefix=["acli", "jira"],
        truncation_hint="Use --limit or --output-format json with fewer fields to reduce output size.",
    )


if __name__ == "__main__":
    mcp.run()
