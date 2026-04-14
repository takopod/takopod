## Tool Usage

- The `gh` CLI is NOT available in this environment. For all GitHub operations (pull requests, issues, repos, CI checks), use the `mcp__github__*` tools. Do NOT attempt to run `gh` commands via Bash.
- When given a GitHub URL like `https://github.com/owner/repo/pull/123`, parse the owner, repo, and number from the URL and call the appropriate MCP tool.

## Available GitHub MCP Tools

- `mcp__github__get_pull_request` — PR metadata (title, description, author, branches)
- `mcp__github__get_pr_files` — list changed files with additions/deletions
- `mcp__github__get_pr_diff` — full unified diff
- `mcp__github__get_pr_checks` — CI check results
- `mcp__github__get_repo_contents` — read files/directories from the repository via API
- `mcp__github__list_pull_requests` — list PRs for a repo
- `mcp__github__search_pull_requests` — search PRs across repos
- `mcp__github__clone_repository` — clone or update a repo in your workspace
- `mcp__github__list_repo_issues` — list issues in a repo
- `mcp__github__get_issue` — get issue details and comments
- `mcp__github__get_workflow_run` — get workflow run details
- `mcp__github__get_workflow_run_jobs` — list jobs and steps for a workflow run
- `mcp__github__get_job_logs` — fetch logs for a specific job
- `mcp__github__rerun_failed_jobs` — re-run failed jobs in a workflow run
- `mcp__github__rerun_workflow` — re-run an entire workflow run
