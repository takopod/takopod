---
name: slack
description: Use Slack MCP tools to send/read messages, manage channels, and interact with threads
---

Use your `mcp__slack__*` tools to interact with Slack.

## Available operations

- **Messages**: send, read, search, react, pin
- **Channels**: list, join, create, get info
- **Threads**: reply in thread, read thread replies
- **Users**: look up user info, list workspace members

## Usage guidance

- Always reply in-thread when responding to an existing conversation — never post top-level unless starting a new topic
- Use `mcp__slack__list_channels` to resolve channel names if you only have an ID
- Keep messages concise and well-formatted — no walls of text
- Use Slack markdown (bold, code blocks, lists) for readability
- When searching messages, use specific terms and time ranges to narrow results
