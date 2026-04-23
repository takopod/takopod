"""GitHub MCP server for takopod.

Exposes a ``gh`` tool that runs GitHub CLI commands on the host, and a
``git_push`` tool that pushes local branches to the owner's GitHub
repositories using ``gh`` as a per-invocation credential helper.

Permission enforcement (approved / needs-approval / denied) lives in the
orchestrator, not here — this server executes whatever it receives.

Requires the ``gh`` CLI to be installed and authenticated on the host
(``gh auth login``).

Usage (standalone testing):
    python -m integrations.github_mcp
"""

from __future__ import annotations

import asyncio
import os
import re
import shlex
from pathlib import Path

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("GitHubIntegration")

SUBPROCESS_TIMEOUT = 300  # seconds
MAX_OUTPUT_BYTES = 100_000  # ~100KB

_GITHUB_REMOTE_RE = re.compile(
    r"(?:https://github\.com/|git@github\.com:)(?P<owner>[^/]+)/(?P<repo>[^/.]+?)(?:\.git)?$"
)


async def _run(
    *args: str,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    timeout: float = SUBPROCESS_TIMEOUT,
) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
        env=env,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=timeout,
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return -1, "", f"Command timed out after {timeout} seconds"
    return proc.returncode or 0, stdout.decode(), stderr.decode()


async def _get_authenticated_user() -> str | None:
    rc, out, _ = await _run("gh", "api", "user", "--jq", ".login")
    if rc == 0 and out.strip():
        return out.strip()
    return None


@mcp.tool()
async def gh(command: str) -> str:
    """Run a GitHub CLI command. Do NOT include the leading "gh" prefix.

    PERMISSION TIERS — commands are classified by their first two tokens:

    Auto-approved (run immediately):
      pr list/view/diff/checks/status, issue list/view/status,
      run list/view, repo view/list, release list/view,
      search repos/issues/prs/commits/code, workflow list/view,
      gist list/view, label list, project list/view

    Requires user approval (the user sees Accept/Deny buttons in chat):
      pr create/merge/close/reopen/edit/comment/review/ready/draft,
      issue create/close/reopen/edit/comment, run rerun/cancel,
      release create/edit/delete, gist create/edit/delete,
      repo fork/clone/create/rename, label create/edit/delete,
      workflow run/enable/disable, project create/edit/delete

    Denied (blocked, will return an error):
      Everything else — including gh api, auth, config, secret, variable,
      repo delete/archive, ssh-key, gpg-key, and any unrecognized commands.

    OUTPUT SIZE — use --json, --limit, and --jq to keep output concise.
    Output over 100KB is truncated. Examples:
      pr list --repo owner/repo --json number,title,url --limit 20
      issue list --repo owner/repo --json number,title --jq '.[].title'

    Args:
        command: The gh subcommand and arguments (without the "gh" prefix).
    """
    try:
        tokens = shlex.split(command)
    except ValueError as exc:
        return f"Error: invalid command syntax: {exc}"

    if not tokens:
        return "Error: empty command"

    proc = await asyncio.create_subprocess_exec(
        "gh", *tokens,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=SUBPROCESS_TIMEOUT,
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return f"Error: command timed out after {SUBPROCESS_TIMEOUT} seconds"

    if proc.returncode != 0:
        return f"Error (exit {proc.returncode}):\n{stderr.decode()}"

    output = stdout.decode()
    if len(stdout) > MAX_OUTPUT_BYTES:
        truncated = stdout[:MAX_OUTPUT_BYTES].decode(errors="replace")
        total_kb = len(stdout) / 1024
        return (
            f"{truncated}\n\n"
            f"--- Output truncated ({total_kb:.0f}KB total). "
            f"Use --limit, --json with fewer fields, or --jq to reduce output size. ---"
        )
    return output


@mcp.tool()
async def git_push(
    repo_path: str,
    remote: str = "origin",
    branch: str = "",
    set_upstream: bool = False,
    force: bool = False,
) -> str:
    """Push a local branch to a GitHub remote. Requires user approval.

    Only pushes to GitHub repositories owned by the authenticated ``gh``
    user (personal repos and forks). Uses ``gh auth token`` as a
    per-invocation credential helper — no changes to the user's git config.

    Args:
        repo_path: Path to the git repository, relative to /workspace
                   (e.g. "quay-11382" or "." for the workspace root).
                   Absolute /workspace/... paths are also accepted.
        remote:    Git remote name (default "origin").
        branch:    Branch to push. Defaults to the current branch.
        set_upstream: If True, adds -u flag to track the remote branch.
        force:     If True, force-push with --force-with-lease.
    """
    workspace = os.environ.get("TAKOPOD_WORKSPACE")
    if not workspace:
        return "Error: TAKOPOD_WORKSPACE not set — cannot resolve repository path."

    workspace_dir = Path(workspace)

    clean = repo_path.strip().rstrip("/")
    if clean.startswith("/workspace/"):
        clean = clean[len("/workspace/"):]
    elif clean == "/workspace":
        clean = ""
    elif clean.startswith("/"):
        return f"Error: absolute paths outside /workspace are not allowed: {repo_path}"

    host_repo = (workspace_dir / clean).resolve() if clean not in ("", ".") else workspace_dir.resolve()

    if not host_repo.is_dir():
        return f"Error: repository not found: {repo_path}"

    try:
        host_repo.relative_to(workspace_dir.resolve())
    except ValueError:
        return f"Error: path escapes workspace: {repo_path}"

    # Handle git worktrees: the .git file contains a gitdir pointer using
    # container paths (/workspace/...) that don't exist on the host.
    # Instead of modifying the file (which would break the container),
    # resolve the host gitdir and use GIT_DIR/GIT_WORK_TREE env vars.
    git_env: dict[str, str] = {}
    dot_git = host_repo / ".git"
    if dot_git.is_file():
        gitdir_line = dot_git.read_text().strip()
        if gitdir_line.startswith("gitdir: /workspace/"):
            host_gitdir = workspace_dir / gitdir_line[len("gitdir: /workspace/"):]
            if host_gitdir.is_dir():
                git_env["GIT_DIR"] = str(host_gitdir)
                git_env["GIT_WORK_TREE"] = str(host_repo)
            else:
                return f"Error: worktree gitdir not found on host: {host_gitdir}"

    def _git_cmd(*args: str) -> list[str]:
        if git_env:
            return ["git", *args]
        return ["git", "-C", str(host_repo), *args]

    def _git_env() -> dict[str, str] | None:
        return {**os.environ, **git_env} if git_env else None

    rc, _, err = await _run(*_git_cmd("rev-parse", "--git-dir"), env=_git_env())
    if rc != 0:
        return f"Error: not a git repository: {repo_path}"

    rc, remote_url, err = await _run(
        *_git_cmd("remote", "get-url", remote), env=_git_env(),
    )
    if rc != 0:
        return f"Error: remote '{remote}' not found: {err.strip()}"

    remote_url = remote_url.strip()
    m = _GITHUB_REMOTE_RE.match(remote_url)
    if not m:
        return f"Error: remote '{remote}' is not a GitHub URL: {remote_url}"

    repo_owner = m.group("owner")
    gh_user = await _get_authenticated_user()
    if not gh_user:
        return "Error: could not determine authenticated GitHub user (is gh logged in?)"

    if repo_owner.lower() != gh_user.lower():
        return (
            f"Error: remote '{remote}' points to {repo_owner}/{m.group('repo')} "
            f"which is not owned by the authenticated user ({gh_user}). "
            f"Only pushes to your own repositories are allowed."
        )

    if not branch:
        rc, branch_out, err = await _run(
            *_git_cmd("rev-parse", "--abbrev-ref", "HEAD"), env=_git_env(),
        )
        if rc != 0:
            return f"Error: could not determine current branch: {err.strip()}"
        branch = branch_out.strip()

    # Ensure remote uses HTTPS so the credential helper works
    if remote_url.startswith("git@"):
        https_url = f"https://github.com/{repo_owner}/{m.group('repo')}.git"
        rc, _, err = await _run(
            *_git_cmd("remote", "set-url", remote, https_url), env=_git_env(),
        )
        if rc != 0:
            return f"Error: failed to convert remote to HTTPS: {err.strip()}"

    push_env = {
        **os.environ,
        **git_env,
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "credential.helper",
        "GIT_CONFIG_VALUE_0": '!/bin/sh -c "echo protocol=https; echo host=github.com; echo username=x-access-token; echo password=$(gh auth token)"',
    }

    push_cmd = _git_cmd("push")
    if set_upstream:
        push_cmd.append("-u")
    if force:
        push_cmd.append("--force-with-lease")
    push_cmd.extend([remote, branch])

    rc, out, err = await _run(*push_cmd, env=push_env, timeout=120)
    if rc != 0:
        return f"Error: git push failed (exit {rc}):\n{err}"

    result = out.strip()
    if err.strip():
        result = f"{result}\n{err.strip()}" if result else err.strip()
    return result or f"Successfully pushed {branch} to {remote}."


if __name__ == "__main__":
    mcp.run()
