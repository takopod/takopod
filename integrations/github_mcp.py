"""GitHub MCP server for rhclaw.

Provides tools to monitor pull requests, inspect CI failures, and restart
workflows.  Runs on the host (orchestrator) side — credentials never enter
worker containers.

Usage (standalone testing):
    GITHUB_PERSONAL_ACCESS_TOKEN=ghp_... python -m integrations.github_mcp
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("GitHubIntegration")

GITHUB_TOKEN = os.environ.get("GITHUB_PERSONAL_ACCESS_TOKEN", "")
GITHUB_USERNAME = os.environ.get("GITHUB_USERNAME", "")


# ---------------------------------------------------------------------------
# HTTP client — all GitHub REST API access goes through this class.
# To swap to PyGithub or requests later, replace this class only.
# ---------------------------------------------------------------------------


class GitHubClient:
    """Thin wrapper around urllib.request for GitHub REST API calls."""

    BASE_URL = "https://api.github.com"

    def __init__(self, token: str) -> None:
        self.token = token

    def _headers(self, accept: str = "application/vnd.github+json") -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": accept,
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        accept: str = "application/vnd.github+json",
    ) -> Any:
        """Make an authenticated GitHub API request.

        Returns parsed JSON for JSON responses, or raw text for non-JSON
        (e.g. log downloads).
        """
        url = f"{self.BASE_URL}{path}"
        if params:
            qs = "&".join(f"{k}={urllib.request.quote(str(v))}" for k, v in params.items() if v)
            if qs:
                url = f"{url}?{qs}"

        req = urllib.request.Request(url, method=method, headers=self._headers(accept))

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = resp.read().decode()
                content_type = resp.headers.get("Content-Type", "")
                if "json" in content_type:
                    return json.loads(body)
                return body
        except urllib.error.HTTPError as exc:
            status = exc.code
            try:
                detail = json.loads(exc.read().decode()).get("message", "")
            except Exception:
                detail = exc.reason
            raise GitHubAPIError(status, detail) from exc

    def get(self, path: str, **kwargs: Any) -> Any:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> Any:
        return self.request("POST", path, **kwargs)


class GitHubAPIError(Exception):
    """Structured error from the GitHub API."""

    def __init__(self, status: int, message: str) -> None:
        self.status = status
        self.message = message
        super().__init__(f"GitHub API error ({status}): {message}")


_client = GitHubClient(GITHUB_TOKEN)


def _api_error_response(exc: GitHubAPIError) -> str:
    """Format a GitHubAPIError into a human-readable tool response."""
    if exc.status == 404:
        return f"Not found: {exc.message}"
    if exc.status == 401:
        return "Authentication failed. Check your GitHub Personal Access Token."
    if exc.status == 403:
        return f"Permission denied: {exc.message}"
    return f"GitHub API error ({exc.status}): {exc.message}"


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
async def list_pull_requests(owner: str, repo: str, state: str = "open") -> str:
    """List pull requests for a repository.

    Args:
        owner: Repository owner (user or org).
        repo: Repository name.
        state: Filter by state — "open", "closed", or "all". Default "open".
    """
    try:
        prs = _client.get(
            f"/repos/{owner}/{repo}/pulls",
            params={"state": state, "per_page": "30"},
        )
    except GitHubAPIError as exc:
        return _api_error_response(exc)

    if not prs:
        return f"No {state} pull requests found in {owner}/{repo}."

    lines = []
    for pr in prs:
        draft = " [DRAFT]" if pr.get("draft") else ""
        lines.append(
            f"#{pr['number']} {pr['title']}{draft}\n"
            f"  Author: {pr['user']['login']}  |  Branch: {pr['head']['ref']}  |  "
            f"Created: {pr['created_at']}"
        )
    return "\n\n".join(lines)


@mcp.tool()
async def search_pull_requests(
    author: str = "", state: str = "", repo: str = "", query: str = "", per_page: int = 10
) -> str:
    """Search pull requests across repositories. Useful for finding your own PRs.

    The authenticated GitHub user is: {username}

    Args:
        author: Filter by PR author username. Leave empty to search all authors.
        state: Filter by state — "open", "closed", or "" for all.
        repo: Filter to a specific repo (format: "owner/repo"). Leave empty for all repos.
        query: Additional search terms (matched against PR title/body).
        per_page: Number of results (max 30, default 10).
    """.format(username=GITHUB_USERNAME or "unknown")
    per_page = min(max(1, per_page), 30)

    q_parts = ["type:pr"]
    if author:
        q_parts.append(f"author:{author}")
    if state in ("open", "closed"):
        q_parts.append(f"state:{state}")
    if repo:
        q_parts.append(f"repo:{repo}")
    if query:
        q_parts.append(query)

    try:
        data = _client.get(
            "/search/issues",
            params={"q": " ".join(q_parts), "sort": "updated", "order": "desc", "per_page": str(per_page)},
        )
    except GitHubAPIError as exc:
        return _api_error_response(exc)

    items = data.get("items", [])
    if not items:
        return "No pull requests found matching your search."

    lines = []
    for pr in items:
        repo_url = pr.get("repository_url", "")
        repo_name = "/".join(repo_url.split("/")[-2:]) if repo_url else "unknown"
        state_str = pr.get("state", "unknown")
        lines.append(
            f"#{pr['number']} {pr['title']}  [{state_str.upper()}]\n"
            f"  Repo: {repo_name}  |  Author: {pr['user']['login']}  |  "
            f"Updated: {pr.get('updated_at', '')}"
        )
    return "\n\n".join(lines)


@mcp.tool()
async def get_pull_request(owner: str, repo: str, pr_number: int) -> str:
    """Get detailed information about a specific pull request.

    Args:
        owner: Repository owner.
        repo: Repository name.
        pr_number: Pull request number.
    """
    try:
        pr = _client.get(f"/repos/{owner}/{repo}/pulls/{pr_number}")
    except GitHubAPIError as exc:
        return _api_error_response(exc)

    reviewers = ", ".join(r["login"] for r in pr.get("requested_reviewers", [])) or "none"
    labels = ", ".join(lb["name"] for lb in pr.get("labels", [])) or "none"

    return (
        f"#{pr['number']} {pr['title']}\n"
        f"State: {pr['state']}  |  Draft: {pr.get('draft', False)}\n"
        f"Author: {pr['user']['login']}\n"
        f"Branch: {pr['head']['ref']} → {pr['base']['ref']}\n"
        f"Mergeable: {pr.get('mergeable', 'unknown')}  |  "
        f"Merge state: {pr.get('mergeable_state', 'unknown')}\n"
        f"Reviewers: {reviewers}\n"
        f"Labels: {labels}\n"
        f"Created: {pr['created_at']}  |  Updated: {pr['updated_at']}\n\n"
        f"{pr.get('body') or '(no description)'}"
    )


@mcp.tool()
async def get_pr_checks(owner: str, repo: str, pr_number: int) -> str:
    """Get CI check results for a pull request.

    Args:
        owner: Repository owner.
        repo: Repository name.
        pr_number: Pull request number.
    """
    try:
        pr = _client.get(f"/repos/{owner}/{repo}/pulls/{pr_number}")
        head_sha = pr["head"]["sha"]
    except GitHubAPIError as exc:
        return _api_error_response(exc)

    lines = [f"Checks for PR #{pr_number} (commit {head_sha[:8]}):"]

    # Check runs (GitHub Actions, third-party apps)
    try:
        checks = _client.get(f"/repos/{owner}/{repo}/commits/{head_sha}/check-runs")
        for cr in checks.get("check_runs", []):
            conclusion = cr.get("conclusion") or cr.get("status", "unknown")
            name = cr["name"]
            lines.append(f"  [{conclusion.upper()}] {name}")
            if conclusion == "failure" and cr.get("output", {}).get("summary"):
                lines.append(f"    Summary: {cr['output']['summary'][:200]}")
    except GitHubAPIError:
        lines.append("  (could not fetch check runs)")

    # Commit statuses (legacy status API)
    try:
        statuses = _client.get(f"/repos/{owner}/{repo}/commits/{head_sha}/status")
        for s in statuses.get("statuses", []):
            lines.append(f"  [{s['state'].upper()}] {s['context']}")
            if s.get("description"):
                lines.append(f"    {s['description'][:200]}")
    except GitHubAPIError:
        lines.append("  (could not fetch commit statuses)")

    if len(lines) == 1:
        lines.append("  No checks found.")

    return "\n".join(lines)


@mcp.tool()
async def get_workflow_run(owner: str, repo: str, run_id: int) -> str:
    """Get details of a specific GitHub Actions workflow run.

    Args:
        owner: Repository owner.
        repo: Repository name.
        run_id: Workflow run ID (visible in check details or run URLs).
    """
    try:
        run = _client.get(f"/repos/{owner}/{repo}/actions/runs/{run_id}")
    except GitHubAPIError as exc:
        return _api_error_response(exc)

    return (
        f"Run #{run['id']}: {run['name']}\n"
        f"Status: {run['status']}  |  Conclusion: {run.get('conclusion', 'pending')}\n"
        f"Branch: {run['head_branch']}  |  Event: {run['event']}\n"
        f"Attempt: {run.get('run_attempt', 1)}\n"
        f"Created: {run['created_at']}  |  Updated: {run['updated_at']}\n"
        f"URL: {run['html_url']}"
    )


@mcp.tool()
async def get_workflow_run_jobs(owner: str, repo: str, run_id: int) -> str:
    """List jobs and their step-level results for a workflow run.

    Args:
        owner: Repository owner.
        repo: Repository name.
        run_id: Workflow run ID.
    """
    try:
        data = _client.get(f"/repos/{owner}/{repo}/actions/runs/{run_id}/jobs")
    except GitHubAPIError as exc:
        return _api_error_response(exc)

    jobs = data.get("jobs", [])
    if not jobs:
        return f"No jobs found for run {run_id}."

    lines = []
    for job in jobs:
        conclusion = job.get("conclusion") or job.get("status", "unknown")
        lines.append(f"Job: {job['name']}  [{conclusion.upper()}]  (ID: {job['id']})")
        for step in job.get("steps", []):
            step_conclusion = step.get("conclusion") or step.get("status", "unknown")
            marker = "FAIL" if step_conclusion == "failure" else step_conclusion.upper()
            lines.append(f"  [{marker}] Step {step['number']}: {step['name']}")
        lines.append("")

    return "\n".join(lines)


@mcp.tool()
async def get_job_logs(owner: str, repo: str, job_id: int) -> str:
    """Fetch logs for a specific job. Useful for debugging failures.

    Args:
        owner: Repository owner.
        repo: Repository name.
        job_id: Job ID (from get_workflow_run_jobs output).
    """
    MAX_LOG_BYTES = 50_000
    MAX_TAIL_LINES = 200

    try:
        raw = _client.get(
            f"/repos/{owner}/{repo}/actions/jobs/{job_id}/logs",
            accept="application/vnd.github+json",
        )
    except GitHubAPIError as exc:
        return _api_error_response(exc)

    if not isinstance(raw, str):
        raw = str(raw)

    if len(raw) > MAX_LOG_BYTES:
        tail = raw.splitlines()[-MAX_TAIL_LINES:]
        return (
            f"[Log truncated — showing last {MAX_TAIL_LINES} lines of {len(raw)} bytes]\n\n"
            + "\n".join(tail)
        )

    return raw


@mcp.tool()
async def rerun_failed_jobs(owner: str, repo: str, run_id: int) -> str:
    """Re-run only the failed jobs in a workflow run.

    Args:
        owner: Repository owner.
        repo: Repository name.
        run_id: Workflow run ID.
    """
    try:
        _client.post(f"/repos/{owner}/{repo}/actions/runs/{run_id}/rerun-failed-jobs")
        return f"Successfully triggered re-run of failed jobs for run {run_id}."
    except GitHubAPIError as exc:
        return _api_error_response(exc)


@mcp.tool()
async def rerun_workflow(owner: str, repo: str, run_id: int) -> str:
    """Re-run an entire workflow run (all jobs).

    Args:
        owner: Repository owner.
        repo: Repository name.
        run_id: Workflow run ID.
    """
    try:
        _client.post(f"/repos/{owner}/{repo}/actions/runs/{run_id}/rerun")
        return f"Successfully triggered full re-run of workflow run {run_id}."
    except GitHubAPIError as exc:
        return _api_error_response(exc)


@mcp.tool()
async def list_repo_issues(
    owner: str, repo: str, state: str = "open", labels: str = "", per_page: int = 20
) -> str:
    """List issues in a repository (excludes pull requests).

    Args:
        owner: Repository owner.
        repo: Repository name.
        state: Filter by state — "open", "closed", or "all". Default "open".
        labels: Comma-separated label names to filter by. Optional.
        per_page: Number of results (max 50, default 20).
    """
    per_page = min(max(1, per_page), 50)
    try:
        items = _client.get(
            f"/repos/{owner}/{repo}/issues",
            params={"state": state, "labels": labels, "per_page": str(per_page)},
        )
    except GitHubAPIError as exc:
        return _api_error_response(exc)

    # GitHub API returns PRs as issues — filter them out
    issues = [i for i in items if "pull_request" not in i]

    if not issues:
        return f"No {state} issues found in {owner}/{repo}."

    lines = []
    for issue in issues:
        issue_labels = ", ".join(lb["name"] for lb in issue.get("labels", []))
        label_str = f"  |  Labels: {issue_labels}" if issue_labels else ""
        lines.append(
            f"#{issue['number']} {issue['title']}\n"
            f"  Author: {issue['user']['login']}{label_str}  |  "
            f"Created: {issue['created_at']}"
        )
    return "\n\n".join(lines)


@mcp.tool()
async def get_issue(owner: str, repo: str, issue_number: int) -> str:
    """Get details and recent comments for a specific issue.

    Args:
        owner: Repository owner.
        repo: Repository name.
        issue_number: Issue number.
    """
    try:
        issue = _client.get(f"/repos/{owner}/{repo}/issues/{issue_number}")
    except GitHubAPIError as exc:
        return _api_error_response(exc)

    labels = ", ".join(lb["name"] for lb in issue.get("labels", [])) or "none"
    assignees = ", ".join(a["login"] for a in issue.get("assignees", [])) or "none"

    parts = [
        f"#{issue['number']} {issue['title']}",
        f"State: {issue['state']}  |  Author: {issue['user']['login']}",
        f"Labels: {labels}  |  Assignees: {assignees}",
        f"Created: {issue['created_at']}  |  Updated: {issue['updated_at']}",
        "",
        issue.get("body") or "(no description)",
    ]

    # Fetch recent comments
    try:
        comments = _client.get(
            f"/repos/{owner}/{repo}/issues/{issue_number}/comments",
            params={"per_page": "20"},
        )
        if comments:
            parts.append(f"\n--- Comments ({len(comments)}) ---")
            for c in comments:
                parts.append(f"\n{c['user']['login']} ({c['created_at']}):\n{c['body']}")
    except GitHubAPIError:
        parts.append("\n(could not fetch comments)")

    return "\n".join(parts)


if __name__ == "__main__":
    mcp.run()
