"""GitHub issues checker — detects new or updated issues matching filters."""

from __future__ import annotations

import asyncio
import json
import logging
import time

from orchestrator.checkers import CheckResult, register

logger = logging.getLogger(__name__)


@register("github_issues", requires_mcp="github")
async def check_github_issues(config: dict, cursor: dict) -> CheckResult:
    repo = config.get("repo", "")
    if not repo:
        return CheckResult(changed=False, new_cursor=cursor, summary="")

    labels = config.get("labels", [])
    state = config.get("state", "open")
    seen_ids: list[int] = cursor.get("seen_ids", [])
    last_checked_at = cursor.get("last_checked_at", "")

    # Build API query
    endpoint = f"repos/{repo}/issues?state={state}&per_page=30&sort=updated&direction=desc"
    if labels:
        endpoint += f"&labels={','.join(labels)}"
    if last_checked_at:
        endpoint += f"&since={last_checked_at}"

    proc = await asyncio.create_subprocess_exec(
        "gh", "api", endpoint,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    if proc.returncode != 0:
        return CheckResult(changed=False, new_cursor=cursor, summary="")

    try:
        issues = json.loads(stdout.decode())
    except json.JSONDecodeError:
        return CheckResult(changed=False, new_cursor=cursor, summary="")

    # Filter out pull requests (GitHub issues API includes PRs)
    issues = [i for i in issues if "pull_request" not in i]

    seen_set = set(seen_ids)
    new_issues = [i for i in issues if i.get("number") not in seen_set]

    if not new_issues:
        return CheckResult(changed=False, new_cursor=cursor, summary="")

    # Update cursor
    new_seen = seen_set | {i["number"] for i in new_issues}

    # Prune: only keep IDs that are still in the current result set
    # (closed issues drop off naturally when state=open)
    current_ids = {i["number"] for i in issues}
    pruned_seen = sorted(new_seen & current_ids) if state != "all" else sorted(new_seen)

    new_cursor = {
        "seen_ids": pruned_seen,
        "last_checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    # Build summary
    lines: list[str] = []
    for i in sorted(new_issues, key=lambda x: x.get("number", 0)):
        number = i.get("number", "?")
        title = i.get("title", "")[:200]
        user = i.get("user", {}).get("login", "unknown")
        issue_labels = [l.get("name", "") for l in i.get("labels", [])]
        label_str = f" [{', '.join(issue_labels)}]" if issue_labels else ""
        lines.append(f"#{number} by @{user}{label_str}: {title}")

    label_filter = f" with labels [{', '.join(labels)}]" if labels else ""
    summary = (
        f"{len(new_issues)} new issue(s) in {repo}{label_filter}:\n\n"
        + "\n".join(lines)
    )
    return CheckResult(changed=True, new_cursor=new_cursor, summary=summary)
