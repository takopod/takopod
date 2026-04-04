-- Allow NULL session_id on agent_containers for scheduled task containers
-- which have no associated session.
PRAGMA foreign_keys = OFF;

CREATE TABLE agent_containers_new (
    id              TEXT PRIMARY KEY,
    agent_id        TEXT NOT NULL REFERENCES agents(id),
    session_id      TEXT REFERENCES sessions(id),
    container_id    TEXT,
    pid             INTEGER,
    container_type  TEXT NOT NULL DEFAULT 'session',
    status          TEXT NOT NULL DEFAULT 'starting',
    started_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    stopped_at      TEXT,
    last_activity   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    error_message   TEXT
);

INSERT INTO agent_containers_new SELECT * FROM agent_containers;
DROP TABLE agent_containers;
ALTER TABLE agent_containers_new RENAME TO agent_containers;

CREATE INDEX idx_agent_containers_agent ON agent_containers(agent_id);
CREATE INDEX idx_agent_containers_session ON agent_containers(session_id);
CREATE INDEX idx_agent_containers_status ON agent_containers(status);

PRAGMA foreign_keys = ON;
