"""Pluggable trigger checkers for agentic tasks.

Each checker polls an external service and returns whether changes were
detected.  The scheduler runs checkers before invoking agents — no LLM
call if nothing changed.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Awaitable, Callable

logger = logging.getLogger(__name__)

SUMMARY_MAX_CHARS = 4000
CHECKER_TIMEOUT = 30  # seconds


@dataclass
class CheckResult:
    changed: bool
    new_cursor: dict
    summary: str


CheckerFn = Callable[[dict, dict], Awaitable[CheckResult]]

CHECKERS: dict[str, CheckerFn] = {}

# Map checker trigger types to the MCP integration name they require.
CHECKER_MCP_GATES: dict[str, str] = {
    "github_pr": "github",
    "github_issues": "github",
    "slack_channel": "slack",
}


def register(trigger_type: str, *, requires_mcp: str | None = None) -> Callable:
    """Decorator to register a checker function."""
    def wrapper(fn: CheckerFn) -> CheckerFn:
        CHECKERS[trigger_type] = fn
        if requires_mcp:
            CHECKER_MCP_GATES[trigger_type] = requires_mcp
        return fn
    return wrapper


def truncate_summary(text: str) -> str:
    if len(text) <= SUMMARY_MAX_CHARS:
        return text
    return text[:SUMMARY_MAX_CHARS - 40] + "\n\n[Summary truncated at 4000 chars]"


async def run_checker(
    trigger_type: str,
    config: dict,
    cursor: dict,
) -> CheckResult:
    """Run a checker with timeout. Returns unchanged on timeout or error."""
    checker = CHECKERS.get(trigger_type)
    if checker is None:
        logger.warning("No checker registered for trigger type: %s", trigger_type)
        return CheckResult(changed=False, new_cursor=cursor, summary="")

    try:
        result = await asyncio.wait_for(
            checker(config, cursor),
            timeout=CHECKER_TIMEOUT,
        )
        if result.summary:
            result.summary = truncate_summary(result.summary)
        return result
    except asyncio.TimeoutError:
        logger.warning("Checker %s timed out after %ds", trigger_type, CHECKER_TIMEOUT)
        return CheckResult(changed=False, new_cursor=cursor, summary="")
    except Exception:
        logger.exception("Checker %s failed", trigger_type)
        return CheckResult(changed=False, new_cursor=cursor, summary="")


# Import checkers to trigger registration.
from orchestrator.checkers import file_watch as _fw  # noqa: F401, E402
from orchestrator.checkers import github_issues as _gi  # noqa: F401, E402
from orchestrator.checkers import github_pr as _gp  # noqa: F401, E402
from orchestrator.checkers import slack_channel as _sc  # noqa: F401, E402
