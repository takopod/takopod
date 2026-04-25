"""Shared subprocess execution helper for CLI-based MCP tools.

Provides a single ``run_cli_tool()`` function that handles shlex parsing,
subprocess creation, timeout/kill, error formatting, and output truncation.
Each MCP server tool calls this instead of duplicating the boilerplate.
"""

from __future__ import annotations

import asyncio
import shlex

SUBPROCESS_TIMEOUT = 300  # seconds
MAX_OUTPUT_BYTES = 100_000  # ~100KB


async def run_cli_tool(
    command: str,
    *,
    cli_prefix: list[str],
    timeout: float = SUBPROCESS_TIMEOUT,
    max_output: int = MAX_OUTPUT_BYTES,
    truncation_hint: str = "...",
) -> str:
    """Execute a CLI command as a subprocess and return its output.

    Args:
        command: The user-provided command string (without the CLI prefix).
        cli_prefix: The CLI binary and any fixed leading arguments
                    (e.g. ``["gh"]`` or ``["acli", "jira"]``).
        timeout: Maximum seconds before the process is killed.
        max_output: Maximum bytes of stdout before truncation.
        truncation_hint: Message appended when output is truncated.

    Returns:
        The command's stdout on success, or a formatted error string.
    """
    try:
        tokens = shlex.split(command)
    except ValueError as exc:
        return f"Error: invalid command syntax: {exc}"

    if not tokens:
        return "Error: empty command"

    proc = await asyncio.create_subprocess_exec(
        *cli_prefix, *tokens,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=timeout,
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return f"Error: command timed out after {timeout} seconds"

    if proc.returncode != 0:
        return f"Error (exit {proc.returncode}):\n{stderr.decode()}"

    if len(stdout) > max_output:
        truncated = stdout[:max_output].decode(errors="replace")
        total_kb = len(stdout) / 1024
        return (
            f"{truncated}\n\n"
            f"--- Output truncated ({total_kb:.0f}KB total). "
            f"{truncation_hint} ---"
        )
    return stdout.decode()
