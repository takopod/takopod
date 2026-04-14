## Tool Usage

- Slack is NOT accessible via CLI or web browser in this environment. For all Slack operations, use the `mcp__slack__*` tools. Do NOT attempt to use `curl` or any other method to access Slack.

## Available Slack MCP Tools

- `mcp__slack__list_channels` — list Slack channels and DMs you belong to
- `mcp__slack__read_channel` — read recent messages from a channel
- `mcp__slack__read_dm` — read recent DMs with a specific user
- `mcp__slack__search_messages` — search messages across all accessible channels
- `mcp__slack__send_note_to_self` — send a private message to your own Slack DM
- `mcp__slack__read_my_notes` — read latest messages from your personal DM history
