"""GitHub PR checker — detects new or updated pull requests, or new activity on a single PR."""

from __future__ import annotations

import asyncio
import json
import logging

from orchestrator.checkers import CheckResult, register

logger = logging.getLogger(__name__)


async def _gh_api(
    endpoint: str,
    *,
    etag: str | None = None,
) -> tuple[int, str, dict[str, str]]:
    """Call gh api and return (exit_code, stdout, response_headers).

    Uses ``gh api -i`` to get response headers for ETag support.
    """
    cmd = ["gh", "api", "-i", endpoint]
    if etag:
        cmd.extend(["--header", f"If-None-Match: {etag}"])

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_bytes, _ = await proc.communicate()
    stdout = stdout_bytes.decode()

    # Parse headers from -i output (status line + headers + blank line + body)
    headers: dict[str, str] = {}
    body = stdout
    if "\r\n\r\n" in stdout:
        header_block, body = stdout.split("\r\n\r\n", 1)
        for line in header_block.splitlines()[1:]:  # skip status line
            if ": " in line:
                k, v = line.split(": ", 1)
                headers[k.lower()] = v

    return proc.returncode or 0, body, headers


@register("github_pr", requires_mcp="github")
async def check_github_pr(config: dict, cursor: dict) -> CheckResult:
    repo = config.get("repo", "")
    if not repo:
        return CheckResult(changed=False, new_cursor=cursor, summary="")

    pr_number = config.get("pr_number")
    if pr_number:
        return await _check_single_pr(repo, pr_number, cursor)
    return await _check_repo_prs(repo, config, cursor)


async def _check_repo_prs(repo: str, config: dict, cursor: dict) -> CheckResult:
    """Check for new or updated PRs across a repository."""
    labels = config.get("labels", [])
    state = config.get("state", "open")
    seen_ids: list[int] = cursor.get("seen_ids", [])

    endpoint = f"repos/{repo}/pulls?state={state}&per_page=30&sort=updated&direction=desc"
    if labels:
        endpoint += f"&labels={','.join(labels)}"

    proc = await asyncio.create_subprocess_exec(
        "gh", "api", endpoint,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        logger.warning(
            "gh api failed for %s PRs (exit %d): %s",
            repo, proc.returncode, stderr.decode().strip()[:200],
        )
        return CheckResult(changed=False, new_cursor=cursor, summary="")

    try:
        prs = json.loads(stdout.decode())
    except json.JSONDecodeError:
        return CheckResult(changed=False, new_cursor=cursor, summary="")

    seen_set = set(seen_ids)
    new_prs = [p for p in prs if p.get("number") not in seen_set]

    if not new_prs:
        return CheckResult(changed=False, new_cursor=cursor, summary="")

    current_ids = {p["number"] for p in prs}
    new_seen = seen_set | {p["number"] for p in new_prs}
    pruned_seen = sorted(new_seen & current_ids) if state != "all" else sorted(new_seen)

    new_cursor = {"seen_ids": pruned_seen}

    lines: list[str] = []
    for p in sorted(new_prs, key=lambda x: x.get("number", 0)):
        number = p.get("number", "?")
        title = p.get("title", "")[:200]
        user = p.get("user", {}).get("login", "unknown")
        pr_labels = [la.get("name", "") for la in p.get("labels", [])]
        label_str = f" [{', '.join(pr_labels)}]" if pr_labels else ""
        lines.append(f"#{number} by @{user}{label_str}: {title}")

    label_filter = f" with labels [{', '.join(labels)}]" if labels else ""
    summary = (
        f"{len(new_prs)} new PR(s) in {repo}{label_filter}:\n\n"
        + "\n".join(lines)
    )
    return CheckResult(changed=True, new_cursor=new_cursor, summary=summary)


async def _check_single_pr(repo: str, pr_number: int, cursor: dict) -> CheckResult:
    """Check for new comments, reviews, and commits on a single PR."""
    changes: list[str] = []
    new_cursor = dict(cursor)

    # Check for new comments
    last_comment_id = cursor.get("last_comment_id", 0)
    rc, body, headers = await _gh_api(
        f"repos/{repo}/issues/{pr_number}/comments?per_page=30&sort=created&direction=desc",
    )
    if rc != 0:
        logger.warning("gh api failed fetching comments for %s#%s (exit %d)", repo, pr_number, rc)
    elif body.strip():
        try:
            comments = json.loads(body)
            new_comments = [c for c in comments if c.get("id", 0) > last_comment_id]
            if new_comments:
                new_cursor["last_comment_id"] = max(c["id"] for c in new_comments)
                for c in sorted(new_comments, key=lambda x: x.get("id", 0)):
                    user = c.get("user", {}).get("login", "unknown")
                    body_text = (c.get("body") or "")[:500]
                    changes.append(f"Comment by @{user}: {body_text}")
        except (json.JSONDecodeError, KeyError):
            logger.warning("Failed to parse PR comments for %s#%s", repo, pr_number)

    # Check for new reviews
    last_review_id = cursor.get("last_review_id", 0)
    rc, body, _ = await _gh_api(
        f"repos/{repo}/pulls/{pr_number}/reviews?per_page=30",
    )
    if rc != 0:
        logger.warning("gh api failed fetching reviews for %s#%s (exit %d)", repo, pr_number, rc)
    elif body.strip():
        try:
            reviews = json.loads(body)
            new_reviews = [r for r in reviews if r.get("id", 0) > last_review_id]
            if new_reviews:
                new_cursor["last_review_id"] = max(r["id"] for r in new_reviews)
                for r in sorted(new_reviews, key=lambda x: x.get("id", 0)):
                    user = r.get("user", {}).get("login", "unknown")
                    state = r.get("state", "unknown")
                    body_text = (r.get("body") or "")[:300]
                    changes.append(f"Review by @{user} ({state}): {body_text}")
        except (json.JSONDecodeError, KeyError):
            logger.warning("Failed to parse PR reviews for %s#%s", repo, pr_number)

    # Check for new commits
    head_sha = cursor.get("head_sha", "")
    rc, body, _ = await _gh_api(
        f"repos/{repo}/pulls/{pr_number}/commits?per_page=30",
    )
    if rc != 0:
        logger.warning("gh api failed fetching commits for %s#%s (exit %d)", repo, pr_number, rc)
    elif body.strip():
        try:
            commits = json.loads(body)
            if commits:
                latest_sha = commits[-1].get("sha", "")
                if latest_sha and latest_sha != head_sha:
                    new_cursor["head_sha"] = latest_sha
                    found_head = not head_sha
                    for c in commits:
                        if not found_head:
                            if c.get("sha") == head_sha:
                                found_head = True
                            continue
                        msg = (c.get("commit", {}).get("message") or "")[:200]
                        author = c.get("commit", {}).get("author", {}).get("name", "unknown")
                        sha_short = c.get("sha", "")[:7]
                        changes.append(f"Commit {sha_short} by {author}: {msg}")
        except (json.JSONDecodeError, KeyError):
            logger.warning("Failed to parse PR commits for %s#%s", repo, pr_number)

    if not changes:
        return CheckResult(changed=False, new_cursor=new_cursor, summary="")

    summary = f"New activity on PR #{pr_number} ({repo}):\n\n" + "\n".join(changes)
    return CheckResult(changed=True, new_cursor=new_cursor, summary=summary)
