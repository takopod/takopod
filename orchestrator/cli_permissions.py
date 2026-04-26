"""Generic permission classification for CLI tool commands.

Provides a single classifier driven by a ``PermissionRuleset``.
Integrations that need no permission gating can pass ``ruleset=None``
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

    If *ruleset* is ``None``, every command is allowed.

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


# ---------------------------------------------------------------------------
# Google Workspace ruleset
# ---------------------------------------------------------------------------
# Command format: <service> <resource> [sub-resource] <method> [flags]
# Gmail and some Sheets/Slides/Chat/Forms commands need depth 4 because of
# an extra resource level (e.g. "gmail users messages list").
# Permanently destructive Gmail operations (messages delete, threads delete)
# are omitted from needs_approval so they fall through to DENIED.

GWS_RULESET = PermissionRuleset(
    allowed=(
        (4, frozenset({
            # Gmail
            "gmail users messages list", "gmail users messages get",
            "gmail users labels list", "gmail users labels get",
            "gmail users drafts list", "gmail users drafts get",
            "gmail users threads list", "gmail users threads get",
            "gmail users history list",
            # Sheets values sub-resource
            "sheets spreadsheets values get", "sheets spreadsheets values batchGet",
            # Slides pages sub-resource
            "slides presentations pages get",
            # Forms responses sub-resource
            "forms forms responses list", "forms forms responses get",
            # Chat sub-resources
            "chat spaces messages list", "chat spaces messages get",
            "chat spaces members list", "chat spaces members get",
        })),
        (3, frozenset({
            # Drive
            "drive files list", "drive files get", "drive files export",
            "drive permissions list", "drive permissions get",
            "drive comments list", "drive comments get",
            "drive replies list", "drive replies get",
            "drive revisions list", "drive revisions get",
            "drive changes list",
            "drive drives list", "drive drives get",
            # Sheets
            "sheets spreadsheets get",
            # Calendar
            "calendar events list", "calendar events get",
            "calendar calendarList list", "calendar calendarList get",
            "calendar colors get",
            "calendar settings list", "calendar settings get",
            # Docs
            "docs documents get",
            # Slides
            "slides presentations get",
            # Tasks
            "tasks tasklists list", "tasks tasklists get",
            "tasks tasks list", "tasks tasks get",
            # People
            "people people get", "people people searchContacts",
            "people people searchDirectoryPeople", "people people listDirectoryPeople",
            "people contactGroups list", "people contactGroups get",
            "people otherContacts list",
            # Chat
            "chat spaces list", "chat spaces get",
            # Forms
            "forms forms get",
        })),
        (1, frozenset({
            "schema",
        })),
    ),
    needs_approval=(
        (4, frozenset({
            # Gmail
            "gmail users messages send", "gmail users messages modify",
            "gmail users messages trash", "gmail users messages untrash",
            "gmail users labels create", "gmail users labels update",
            "gmail users labels patch", "gmail users labels delete",
            "gmail users drafts create", "gmail users drafts update",
            "gmail users drafts send", "gmail users drafts delete",
            "gmail users threads modify",
            "gmail users threads trash", "gmail users threads untrash",
            # Sheets values sub-resource
            "sheets spreadsheets values update", "sheets spreadsheets values append",
            "sheets spreadsheets values batchUpdate",
            "sheets spreadsheets values clear", "sheets spreadsheets values batchClear",
            # Slides pages sub-resource
            "slides presentations pages delete",
            # Chat sub-resources
            "chat spaces messages create", "chat spaces messages update",
            "chat spaces messages delete",
            "chat spaces members create", "chat spaces members delete",
        })),
        (3, frozenset({
            # Drive
            "drive files create", "drive files update",
            "drive files copy", "drive files delete",
            "drive permissions create", "drive permissions update",
            "drive permissions delete",
            "drive comments create", "drive comments update", "drive comments delete",
            "drive replies create", "drive replies update", "drive replies delete",
            "drive drives create", "drive drives update", "drive drives delete",
            # Sheets
            "sheets spreadsheets create", "sheets spreadsheets batchUpdate",
            # Calendar
            "calendar events insert", "calendar events update",
            "calendar events patch", "calendar events delete",
            "calendar events quickAdd",
            "calendar calendarList insert", "calendar calendarList update",
            "calendar calendarList patch", "calendar calendarList delete",
            # Docs
            "docs documents create", "docs documents batchUpdate",
            # Slides
            "slides presentations create", "slides presentations batchUpdate",
            # Tasks
            "tasks tasklists insert", "tasks tasklists update",
            "tasks tasklists patch", "tasks tasklists delete",
            "tasks tasks insert", "tasks tasks update",
            "tasks tasks patch", "tasks tasks delete", "tasks tasks clear",
            # People
            "people people createContact", "people people updateContact",
            "people people deleteContact",
            "people contactGroups create", "people contactGroups update",
            "people contactGroups delete",
            # Chat
            "chat spaces create", "chat spaces delete", "chat spaces setup",
            # Forms
            "forms forms create", "forms forms batchUpdate",
        })),
    ),
    denied_groups=frozenset({"auth"}),
)
