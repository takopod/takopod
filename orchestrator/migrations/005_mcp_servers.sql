-- MCP server registry and per-agent join table.
-- Replaces data/mcp-defaults.json, data/mcp-configs/*.json,
-- and agents.slack_enabled / agents.github_enabled columns.

CREATE TABLE IF NOT EXISTS mcp_servers (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL UNIQUE,
    transport  TEXT NOT NULL DEFAULT 'stdio',
    command    TEXT NOT NULL DEFAULT '',
    args       TEXT NOT NULL DEFAULT '[]',
    url        TEXT NOT NULL DEFAULT '',
    auth       TEXT NOT NULL DEFAULT 'none',
    env        TEXT NOT NULL DEFAULT '{}',
    timeout    REAL NOT NULL DEFAULT 30.0,
    builtin    INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS agent_mcp_servers (
    agent_id      TEXT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    mcp_server_id TEXT NOT NULL REFERENCES mcp_servers(id) ON DELETE CASCADE,
    enabled       INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (agent_id, mcp_server_id)
);

-- Drop slack_enabled and github_enabled from agents table.
CREATE TABLE IF NOT EXISTS agents_new (
    id               TEXT PRIMARY KEY,
    name             TEXT NOT NULL,
    icon             TEXT NOT NULL DEFAULT '',
    host_dir         TEXT NOT NULL,
    container_memory TEXT NOT NULL DEFAULT '2g',
    container_cpus   TEXT NOT NULL DEFAULT '2',
    created_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    status           TEXT NOT NULL DEFAULT 'active'
);

INSERT OR IGNORE INTO agents_new (id, name, icon, host_dir, container_memory, container_cpus, created_at, status)
    SELECT id, name, icon, host_dir, container_memory, container_cpus, created_at, status FROM agents;

DROP TABLE agents;
ALTER TABLE agents_new RENAME TO agents;

CREATE UNIQUE INDEX IF NOT EXISTS idx_agents_name_unique ON agents(name);
