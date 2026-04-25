"""Generic permission classification for CLI tool commands.

Provides a single classifier driven by a ``PermissionRuleset``.
Integrations that need no permission gating (e.g. GWS) pass ``ruleset=None``
and get ``ALLOWED`` for every command.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass, field
from enum import Enum


class CliPermission(str, Enum):
    ALLOWED = "allowed"
    NEEDS_APPROVAL = "needs_approval"
    DENIED = "denied"


@dataclass(frozen=True)
class PermissionRuleset:
    """Declares which command prefixes are allowed, need approval, or denied.

    Each of ``allowed`` and ``needs_approval`` is a tuple of
    ``(token_depth, frozenset_of_prefixes)`` entries.  The classifier tries
    the longest token depth first, then falls back to shorter ones.

    ``denied_groups`` names top-level tokens whose *entire* subtree is denied
    (e.g. ``"auth"`` blocks ``auth login``, ``auth logout``, etc.).
    """

    allowed: tuple[tuple[int, frozenset[str]], ...] = ()
    needs_approval: tuple[tuple[int, frozenset[str]], ...] = ()
    denied_groups: frozenset[str] = field(default_factory=frozenset)


def classify_command(
    command: str, ruleset: PermissionRuleset | None,
) -> tuple[CliPermission, str]:
    """Classify *command* against *ruleset*.

    If *ruleset* is ``None``, every command is allowed (GWS case).

    Returns ``(permission, matched_prefix)`` where *matched_prefix* is the
    token prefix that triggered the decision.
    """
    if ruleset is None:
        return CliPermission.ALLOWED, command

    try:
        tokens = shlex.split(command)
    except ValueError:
        return CliPermission.DENIED, command

    if not tokens:
        return CliPermission.DENIED, ""

    first = tokens[0]

    # Deny entire groups (e.g. "auth login", "auth logout", etc.)
    if first in ruleset.denied_groups:
        matched = f"{first} {tokens[1]}" if len(tokens) >= 2 else first
        return CliPermission.DENIED, matched

    # Collect all token depths present in the ruleset, sorted longest first
    depths: set[int] = set()
    for depth, _ in ruleset.allowed:
        depths.add(depth)
    for depth, _ in ruleset.needs_approval:
        depths.add(depth)

    for depth in sorted(depths, reverse=True):
        if len(tokens) < depth:
            continue
        prefix = " ".join(tokens[:depth])
        for d, cmds in ruleset.allowed:
            if d == depth and prefix in cmds:
                return CliPermission.ALLOWED, prefix
        for d, cmds in ruleset.needs_approval:
            if d == depth and prefix in cmds:
                return CliPermission.NEEDS_APPROVAL, prefix

    # Fall back: build the longest possible prefix for the denial message
    max_depth = max(depths) if depths else 2
    prefix = " ".join(tokens[:min(len(tokens), max_depth)])
    return CliPermission.DENIED, prefix


# ---------------------------------------------------------------------------
# GitHub ruleset
# ---------------------------------------------------------------------------

GH_RULESET = PermissionRuleset(
    allowed=(
        (2, frozenset({
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
        })),
    ),
    needs_approval=(
        (2, frozenset({
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
        })),
    ),
)


# ---------------------------------------------------------------------------
# Jira ruleset
# ---------------------------------------------------------------------------

JIRA_RULESET = PermissionRuleset(
    allowed=(
        (3, frozenset({
            "workitem comment list", "workitem comment visibility",
            "workitem link list", "workitem link type",
            "workitem attachment list",
            "workitem watcher list",
        })),
        (2, frozenset({
            "workitem search", "workitem view",
            "sprint view", "sprint list-workitems",
            "board get", "board search", "board list-projects", "board list-sprints",
            "project list", "project view",
            "filter get", "filter get-columns", "filter list", "filter search",
            "dashboard search",
        })),
    ),
    needs_approval=(
        (3, frozenset({
            "workitem comment create", "workitem comment update", "workitem comment delete",
            "workitem link create", "workitem link delete",
            "workitem attachment delete",
            "workitem watcher remove",
        })),
        (2, frozenset({
            "workitem create", "workitem edit", "workitem assign",
            "workitem transition", "workitem clone", "workitem create-bulk",
            "sprint create", "sprint update", "sprint delete",
            "board create", "board delete",
            "project create", "project update",
            "filter add-favourite", "filter change-owner", "filter update",
            "filter reset-columns",
            "field create", "field cancel-delete",
        })),
    ),
    denied_groups=frozenset({"auth"}),
)
