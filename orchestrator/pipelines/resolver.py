"""Template variable resolution for pipeline configs.

Resolves placeholders like {profile.name}, {profile.commands.test_all},
{artifacts_dir}, {run_id} in agent prompts and workflow prose.
"""

from __future__ import annotations

import re
from typing import Any


_VAR_PATTERN = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_.]*)\}")


def _resolve_dotted_key(context: dict[str, Any], key: str) -> str:
    """Resolve a dotted key path against a nested dict.

    Example: "profile.commands.test_all" resolves
    context["profile"]["commands"]["test_all"].
    """
    parts = key.split(".")
    current: Any = context
    for i, part in enumerate(parts):
        if isinstance(current, dict):
            if part not in current:
                raise KeyError(
                    f"Template variable '{{{key}}}' not found: "
                    f"key '{part}' missing from {list(current.keys())}"
                )
            current = current[part]
        else:
            raise KeyError(
                f"Template variable '{{{key}}}' not found: "
                f"'{'.'.join(parts[:i])}' is not a dict"
            )
    return str(current)


def resolve(template: str, context: dict[str, Any]) -> str:
    """Resolve all {var.path} placeholders in a template string.

    Args:
        template: String with {variable} placeholders.
        context: Nested dict of values. Top-level keys are namespaces
                 (e.g. "profile", "artifacts_dir", "run_id").

    Returns:
        Resolved string with all placeholders substituted.

    Raises:
        KeyError: If a placeholder references a missing key, with a
                  message identifying which variable failed.
    """
    # First, temporarily replace escaped braces so they survive resolution
    template = template.replace("{{", "\x00LBRACE\x00")
    template = template.replace("}}", "\x00RBRACE\x00")

    def replacer(match: re.Match[str]) -> str:
        key = match.group(1)
        return _resolve_dotted_key(context, key)

    result = _VAR_PATTERN.sub(replacer, template)

    # Restore escaped braces as literal { and }
    result = result.replace("\x00LBRACE\x00", "{")
    result = result.replace("\x00RBRACE\x00", "}")
    return result


def build_context(
    profile: dict[str, Any],
    artifacts_dir: str,
    extracted_vars: dict[str, str],
) -> dict[str, Any]:
    """Build the template resolution context from pipeline components.

    Args:
        profile: Parsed profile.yaml as a dict.
        artifacts_dir: Resolved artifact directory path.
        extracted_vars: Variables captured from trigger match (e.g. run_id).

    Returns:
        Context dict for resolve().
    """
    ctx: dict[str, Any] = {
        "profile": profile,
        "artifacts_dir": artifacts_dir,
    }
    ctx.update(extracted_vars)
    return ctx
