-- Persistent agent instances with workspace directories and identity files
CREATE TABLE IF NOT EXISTS agents (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
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

-- Recreate agent_containers with agent_id reference, dropping agent_type and host_dir
CREATE TABLE IF NOT EXISTS agent_containers_new (
    id              TEXT PRIMARY KEY,
    agent_id        TEXT NOT NULL REFERENCES agents(id),
    session_id      TEXT NOT NULL REFERENCES sessions(id),
    container_id    TEXT,
    pid             INTEGER,
    container_type  TEXT NOT NULL DEFAULT 'session',
    status          TEXT NOT NULL DEFAULT 'starting',
    started_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    stopped_at      TEXT,
    last_activity   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    error_message   TEXT
);

DROP TABLE IF EXISTS agent_containers;
ALTER TABLE agent_containers_new RENAME TO agent_containers;

CREATE INDEX IF NOT EXISTS idx_agent_containers_agent ON agent_containers(agent_id);
CREATE INDEX IF NOT EXISTS idx_agent_containers_session ON agent_containers(session_id);
CREATE INDEX IF NOT EXISTS idx_agent_containers_status ON agent_containers(status);
