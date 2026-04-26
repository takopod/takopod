"""Registry of CLI tool gates for the IPC permission layer.

Each entry maps an ``(mcp_server_name, tool_name)`` pair to a
``CliToolGate`` that knows how to classify the command and what
approval source / display prefix to use.

The IPC handler in ``ipc.py`` does a single dict lookup instead of
maintaining per-integration ``if`` blocks.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from orchestrator.cli_permissions import (
    CliPermission,
    GH_RULESET,
    GWS_RULESET,
    JIRA_RULESET,
    PermissionRuleset,
    classify_command,
)


@dataclass(frozen=True)
class CliToolGate:
    """Describes how the IPC layer should gate a single CLI tool."""

    ruleset: PermissionRuleset | None = None
    approval_source: str | None = None
    cli_prefix: str = ""
    always_approve: bool = False
    describe: Callable[[dict], str] | None = None

    def classify(self, command: str) -> tuple[CliPermission, str]:
        """Classify *command* for this gate.

        If ``always_approve`` is set, every command requires approval
        (used for ``git_push``).
        """
        if self.always_approve:
            return CliPermission.NEEDS_APPROVAL, command
        return classify_command(command, self.ruleset)


def _describe_git_push(arguments: dict) -> str:
    """Build a human-readable description for a git_push approval request."""
    repo = arguments.get("repo_path", "")
    remote = arguments.get("remote", "origin")
    branch = arguments.get("branch", "(current)")
    return f"git push {repo} → {remote} {branch}"


CLI_TOOL_GATES: dict[tuple[str, str], CliToolGate] = {
    ("github", "gh"): CliToolGate(
        ruleset=GH_RULESET,
        approval_source="github",
        cli_prefix="gh",
    ),
    ("github", "git_push"): CliToolGate(
        always_approve=True,
        approval_source="github",
        cli_prefix="git push",
        describe=_describe_git_push,
    ),
    ("jira", "jira"): CliToolGate(
        ruleset=JIRA_RULESET,
        approval_source="jira",
        cli_prefix="acli jira",
    ),
    ("gws", "gws"): CliToolGate(
        ruleset=GWS_RULESET,
        approval_source="gws",
        cli_prefix="gws",
    ),
}
