"""Permission classification for acli jira commands.

Only commands explicitly listed in ALLOWED or NEEDS_APPROVAL are permitted.
Everything else is denied by default.

Jira commands use nested subcommands (e.g. ``workitem comment create``),
so classification first tries a 3-token match, then falls back to 2-token.
"""

from __future__ import annotations

import shlex
from enum import Enum

# 3-token commands (nested subcommands like "workitem comment list")
ALLOWED_JIRA_COMMANDS_3: frozenset[str] = frozenset({
    "workitem comment list", "workitem comment visibility",
    "workitem link list", "workitem link type",
    "workitem attachment list",
    "workitem watcher list",
})

NEEDS_APPROVAL_JIRA_COMMANDS_3: frozenset[str] = frozenset({
    "workitem comment create", "workitem comment update", "workitem comment delete",
    "workitem link create", "workitem link delete",
    "workitem attachment delete",
    "workitem watcher remove",
})

# 2-token commands (top-level subcommands like "workitem search")
ALLOWED_JIRA_COMMANDS_2: frozenset[str] = frozenset({
    "workitem search", "workitem view",
    "sprint view", "sprint list-workitems",
    "board get", "board search", "board list-projects", "board list-sprints",
    "project list", "project view",
    "filter get", "filter get-columns", "filter list", "filter search",
    "dashboard search",
})

NEEDS_APPROVAL_JIRA_COMMANDS_2: frozenset[str] = frozenset({
    "workitem create", "workitem edit", "workitem assign",
    "workitem transition", "workitem clone", "workitem create-bulk",
    "sprint create", "sprint update", "sprint delete",
    "board create", "board delete",
    "project create", "project update",
    "filter add-favourite", "filter change-owner", "filter update",
    "filter reset-columns",
    "field create", "field cancel-delete",
})

# Explicitly denied top-level groups (all subcommands blocked)
_DENIED_GROUPS: frozenset[str] = frozenset({
    "auth",
})


class JiraPermission(str, Enum):
    ALLOWED = "allowed"
    NEEDS_APPROVAL = "needs_approval"
    DENIED = "denied"


def classify_jira_command(command: str) -> tuple[JiraPermission, str]:
    """Classify a Jira command string into a permission tier.

    Returns (permission_level, matched_prefix).
    Commands not in either allowlist are denied by default.
    """
    try:
        tokens = shlex.split(command)
    except ValueError:
        return JiraPermission.DENIED, command

    if not tokens:
        return JiraPermission.DENIED, ""

    first = tokens[0]

    # Deny entire groups (e.g. "auth login", "auth logout", etc.)
    if first in _DENIED_GROUPS:
        matched = f"{first} {tokens[1]}" if len(tokens) >= 2 else first
        return JiraPermission.DENIED, matched

    if len(tokens) < 2:
        return JiraPermission.DENIED, first

    # Try 3-token match first for nested subcommands
    if len(tokens) >= 3:
        prefix3 = f"{tokens[0]} {tokens[1]} {tokens[2]}"
        if prefix3 in ALLOWED_JIRA_COMMANDS_3:
            return JiraPermission.ALLOWED, prefix3
        if prefix3 in NEEDS_APPROVAL_JIRA_COMMANDS_3:
            return JiraPermission.NEEDS_APPROVAL, prefix3

    # Fall back to 2-token match
    prefix2 = f"{tokens[0]} {tokens[1]}"
    if prefix2 in ALLOWED_JIRA_COMMANDS_2:
        return JiraPermission.ALLOWED, prefix2
    if prefix2 in NEEDS_APPROVAL_JIRA_COMMANDS_2:
        return JiraPermission.NEEDS_APPROVAL, prefix2

    return JiraPermission.DENIED, prefix2
