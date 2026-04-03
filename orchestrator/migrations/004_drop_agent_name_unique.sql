-- Remove UNIQUE constraint from agents.name (UUID is the real identifier)
-- Must disable FK checks since agent_containers references agents(id).
PRAGMA foreign_keys = OFF;

CREATE TABLE agents_new (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    agent_type  TEXT NOT NULL DEFAULT 'default',
    host_dir    TEXT NOT NULL,
    claude_md   TEXT,
    soul_md     TEXT,
    memory_md   TEXT,
    container_memory TEXT NOT NULL DEFAULT '2g',
    container_cpus   TEXT NOT NULL DEFAULT '2',
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    status      TEXT NOT NULL DEFAULT 'active'
);

INSERT INTO agents_new SELECT * FROM agents;
DROP TABLE agents;
ALTER TABLE agents_new RENAME TO agents;

PRAGMA foreign_keys = ON;
