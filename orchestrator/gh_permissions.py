"""Permission classification for gh CLI commands.

Only commands explicitly listed in APPROVED or ASK_HUMAN_APPROVAL are allowed.
Everything else is denied by default.
"""

from __future__ import annotations

import shlex
from enum import Enum

APPROVED_GH_COMMANDS: frozenset[str] = frozenset({
    "pr list", "pr view", "pr diff", "pr checks", "pr status",
    "issue list", "issue view", "issue status",
    "run list", "run view",
    "repo view", "repo list",
    "release list", "release view",
    "search repos", "search issues", "search prs", "search commits", "search code",
    "workflow list", "workflow view",
    "gist list", "gist view",
    "label list",
    "project list", "project view",
})

ASK_HUMAN_APPROVAL_GH_COMMANDS: frozenset[str] = frozenset({
    "pr create", "pr merge", "pr close", "pr reopen", "pr edit", "pr comment", "pr review",
    "pr ready", "pr draft",
    "issue create", "issue close", "issue reopen", "issue edit", "issue comment",
    "run rerun", "run cancel",
    "release create", "release edit", "release delete",
    "gist create", "gist edit", "gist delete",
    "repo fork", "repo clone", "repo create", "repo rename",
    "label create", "label edit", "label delete",
    "workflow run", "workflow enable", "workflow disable",
    "project create", "project edit", "project delete",
})


class GhPermission(str, Enum):
    ALLOWED = "allowed"
    NEEDS_APPROVAL = "needs_approval"
    DENIED = "denied"


def classify_gh_command(command: str) -> tuple[GhPermission, str]:
    """Classify a gh command string into a permission tier.

    Returns (permission_level, matched_prefix).
    Commands not in either allowlist are denied by default.
    """
    try:
        tokens = shlex.split(command)
    except ValueError:
        return GhPermission.DENIED, command

    if not tokens:
        return GhPermission.DENIED, ""

    first = tokens[0]

    if len(tokens) < 2:
        return GhPermission.DENIED, first

    prefix = f"{first} {tokens[1]}"

    if prefix in APPROVED_GH_COMMANDS:
        return GhPermission.ALLOWED, prefix
    if prefix in ASK_HUMAN_APPROVAL_GH_COMMANDS:
        return GhPermission.NEEDS_APPROVAL, prefix

    return GhPermission.DENIED, prefix
