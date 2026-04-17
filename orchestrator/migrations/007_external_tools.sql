CREATE TABLE IF NOT EXISTS external_tools (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL UNIQUE,
    config     TEXT NOT NULL DEFAULT '{}',
    builtin    INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS agent_external_tools (
    agent_id         TEXT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    external_tool_id TEXT NOT NULL REFERENCES external_tools(id) ON DELETE CASCADE,
    enabled          INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (agent_id, external_tool_id)
);
