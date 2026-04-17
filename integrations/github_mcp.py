"""GitHub MCP server for rhclaw.

Exposes a single ``gh`` tool that runs GitHub CLI commands on the host.
Permission enforcement (approved / needs-approval / denied) lives in the
orchestrator, not here — this server executes whatever it receives.

Requires the ``gh`` CLI to be installed and authenticated on the host
(``gh auth login``).

Usage (standalone testing):
    python -m integrations.github_mcp
"""

from __future__ import annotations

import asyncio
import shlex

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("GitHubIntegration")

SUBPROCESS_TIMEOUT = 300  # seconds
MAX_OUTPUT_BYTES = 100_000  # ~100KB


@mcp.tool()
async def gh(command: str) -> str:
    """Run a GitHub CLI command. Do NOT include the leading "gh" prefix.

    PERMISSION TIERS — commands are classified by their first two tokens:

    Auto-approved (run immediately):
      pr list/view/diff/checks/status, issue list/view/status,
      run list/view, repo view/list, release list/view,
      search repos/issues/prs/commits/code, workflow list/view,
      gist list/view, label list, project list/view

    Requires user approval (the user sees Accept/Deny buttons in chat):
      pr create/merge/close/reopen/edit/comment/review/ready/draft,
      issue create/close/reopen/edit/comment, run rerun/cancel,
      release create/edit/delete, gist create/edit/delete,
      repo fork/clone/create/rename, label create/edit/delete,
      workflow run/enable/disable, project create/edit/delete

    Denied (blocked, will return an error):
      Everything else — including gh api, auth, config, secret, variable,
      repo delete/archive, ssh-key, gpg-key, and any unrecognized commands.

    OUTPUT SIZE — use --json, --limit, and --jq to keep output concise.
    Output over 100KB is truncated. Examples:
      pr list --repo owner/repo --json number,title,url --limit 20
      issue list --repo owner/repo --json number,title --jq '.[].title'

    Args:
        command: The gh subcommand and arguments (without the "gh" prefix).
    """
    try:
        tokens = shlex.split(command)
    except ValueError as exc:
        return f"Error: invalid command syntax: {exc}"

    if not tokens:
        return "Error: empty command"

    proc = await asyncio.create_subprocess_exec(
        "gh", *tokens,
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
            f"Use --limit, --json with fewer fields, or --jq to reduce output size. ---"
        )
    return output


if __name__ == "__main__":
    mcp.run()
