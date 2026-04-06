-- Add slack_enabled flag to agents table.
-- When 1, the orchestrator injects the Slack MCP server into the agent's session.
ALTER TABLE agents ADD COLUMN slack_enabled INTEGER NOT NULL DEFAULT 0;
