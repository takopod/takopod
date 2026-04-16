---
name: jira
description: Use Jira MCP tools to manage issues, search with JQL, and track project work
---

Use your `mcp__jira__*` tools to interact with Jira.

## Available operations

- **Issues**: create, update, transition, comment, assign, link
- **Search**: query with JQL, filter by project/status/assignee
- **Projects**: list, get details, list issue types
- **Sprints/boards**: list sprints, get board contents

## Usage guidance

- Use JQL for complex queries rather than chaining multiple list calls (e.g., `project = FOO AND status = "In Progress" AND assignee = currentUser()`)
- Always include the project key in issue references (e.g., `PROJ-123`, not just `123`)
- When creating issues, ask for or infer: project, issue type, summary, and description at minimum
- Check existing issues before creating duplicates — search by summary keywords first
- When transitioning issues, verify available transitions first — not all workflows allow direct jumps between statuses
