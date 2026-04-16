---
name: github
description: Use GitHub MCP tools to manage repos, issues, PRs, code search, and reviews
---

Use your `mcp__github__*` tools to interact with GitHub.

## Available operations

- **Repos**: clone, search code, read file contents, list branches/tags
- **Issues**: create, update, search, comment, label, assign
- **Pull requests**: create, review, list files/diff, check CI status, merge
- **Code search**: search across repos by keyword, language, or path

## Usage guidance

- Clone repos with `mcp__github__clone_repository` for deep local analysis — use `Read`, `Grep`, `Glob` on the local clone rather than fetching files one-by-one via API
- Prefer `mcp__github__search_code` before asking the user for file paths
- Check for duplicate issues before creating new ones
- Always specify owner and repo explicitly — never assume defaults
- When reviewing PRs, fetch both the diff and the changed file list for full context
