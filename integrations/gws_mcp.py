"""Google Workspace MCP server for takopod.

Exposes a single ``gws`` tool that runs Google Workspace CLI commands on the
host.  All commands are auto-approved — no permission tiers.

Requires the ``gws`` CLI to be installed and authenticated on the host
(``gws auth login``).

Usage (standalone testing):
    python -m integrations.gws_mcp
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from integrations.cli_base import run_cli_tool

mcp = FastMCP("GWSIntegration")


@mcp.tool()
async def gws(command: str) -> str:
    """Run a Google Workspace CLI command. Do NOT include the leading "gws" prefix.

    All commands are auto-approved and execute immediately.

    SERVICES:
      drive        — files, folders, shared drives
      sheets       — read/write spreadsheets
      gmail        — send, read, manage email
      calendar     — manage calendars and events
      docs         — read/write Google Docs
      slides       — read/write presentations
      tasks        — manage task lists and tasks
      people       — manage contacts and profiles
      chat         — manage Chat spaces and messages
      forms        — read/write Google Forms

    COMMAND FORMAT:
      <service> <resource> [sub-resource] <method> [flags]

    EXAMPLES:
      drive files list --params '{"pageSize": 10}'
      gmail users messages list --params '{"userId": "me"}'
      sheets spreadsheets get --params '{"spreadsheetId": "..."}'
      calendar events list --params '{"calendarId": "primary"}'
      schema drive.files.list

    FLAGS:
      --params <JSON>   URL/Query parameters
      --json <JSON>     Request body (POST/PATCH/PUT)
      --format <FMT>    Output format: json (default), table, yaml, csv
      --page-all        Auto-paginate (NDJSON output)
      --page-limit <N>  Max pages (default: 10)

    OUTPUT SIZE — use --format, --page-limit, and targeted --params to keep
    output concise.  Output over 100KB is truncated.

    Args:
        command: The gws subcommand and arguments (without the "gws" prefix).
    """
    return await run_cli_tool(
        command,
        cli_prefix=["gws"],
        truncation_hint="Use --page-limit, --format, or targeted --params to reduce output size.",
    )


if __name__ == "__main__":
    mcp.run()
