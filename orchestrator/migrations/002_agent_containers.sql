CREATE TABLE IF NOT EXISTS agent_containers (
    id              TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL REFERENCES sessions(id),
    container_id    TEXT,
    pid             INTEGER,
    agent_type      TEXT NOT NULL,
    container_type  TEXT NOT NULL DEFAULT 'session',
    host_dir        TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'starting',
    started_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    stopped_at      TEXT,
    last_activity   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    error_message   TEXT
);
CREATE INDEX IF NOT EXISTS idx_agent_containers_session ON agent_containers(session_id);
CREATE INDEX IF NOT EXISTS idx_agent_containers_status ON agent_containers(status);
