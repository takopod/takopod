"""Google Workspace MCP server for takopod.

Exposes a single ``gws`` tool that runs Google Workspace CLI commands on the
host.

Permission enforcement (allowed / needs-approval / denied) lives in the
orchestrator, not here — this server executes whatever it receives.

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

    PERMISSION TIERS — commands are classified by their first 3-4 tokens:

    Auto-approved (run immediately):
      drive files/permissions/comments/replies/revisions list/get,
      drive files export, drive changes list, drive drives list/get,
      sheets spreadsheets get, sheets spreadsheets values get/batchGet,
      calendar events/calendarList list/get, calendar colors/settings get,
      docs documents get, slides presentations get, slides presentations pages get,
      tasks tasklists/tasks list/get,
      people people get/searchContacts/searchDirectoryPeople/listDirectoryPeople,
      people contactGroups list/get, people otherContacts list,
      gmail users messages/labels/drafts/threads list/get, gmail users history list,
      chat spaces list/get, chat spaces messages/members list/get,
      forms forms get, forms forms responses list/get,
      schema

    Requires user approval (the user sees Accept/Deny buttons in chat):
      drive files create/update/copy/delete, drive permissions/comments/replies create/update/delete,
      drive drives create/update/delete,
      sheets spreadsheets create/batchUpdate, sheets spreadsheets values update/append/clear/batchUpdate/batchClear,
      calendar events insert/update/patch/delete/quickAdd, calendar calendarList insert/update/patch/delete,
      docs documents create/batchUpdate, slides presentations create/batchUpdate, slides presentations pages delete,
      tasks tasklists/tasks insert/update/patch/delete, tasks tasks clear,
      people people createContact/updateContact/deleteContact, people contactGroups create/update/delete,
      gmail users messages send/modify/trash/untrash, gmail users labels/drafts create/update/patch/delete,
      gmail users drafts send, gmail users threads modify/trash/untrash,
      chat spaces create/delete/setup, chat spaces messages/members create/update/delete,
      forms forms create/batchUpdate

    Denied (blocked, will return an error):
      gmail users messages delete (permanent — use trash instead),
      gmail users threads delete (permanent — use trash instead),
      auth (all subcommands), and any unrecognized commands.

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
