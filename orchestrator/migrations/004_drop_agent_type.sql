-- Drop the agent_type column from agents table.
-- SQLite doesn't support DROP COLUMN before 3.35.0, so recreate the table.

CREATE TABLE IF NOT EXISTS agents_new (
    id               TEXT PRIMARY KEY,
    name             TEXT NOT NULL,
    icon             TEXT NOT NULL DEFAULT '',
    host_dir         TEXT NOT NULL,
    container_memory TEXT NOT NULL DEFAULT '2g',
    container_cpus   TEXT NOT NULL DEFAULT '2',
    slack_enabled    INTEGER NOT NULL DEFAULT 0,
    github_enabled   INTEGER NOT NULL DEFAULT 0,
    created_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    status           TEXT NOT NULL DEFAULT 'active'
);

INSERT OR IGNORE INTO agents_new (id, name, icon, host_dir, container_memory, container_cpus, slack_enabled, github_enabled, created_at, status)
    SELECT id, name, icon, host_dir, container_memory, container_cpus, slack_enabled, github_enabled, created_at, status FROM agents;

DROP TABLE agents;
ALTER TABLE agents_new RENAME TO agents;

CREATE UNIQUE INDEX IF NOT EXISTS idx_agents_name_unique ON agents(name);
