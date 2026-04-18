-- Consolidated schema: agents, messages, containers, schedules, skills, settings,
-- Slack polling/threads, MCP servers.
-- No sessions table — messages and queues reference agents directly.

CREATE TABLE IF NOT EXISTS agents (
    id               TEXT PRIMARY KEY,
    name             TEXT NOT NULL,
    icon             TEXT NOT NULL DEFAULT '',
    host_dir         TEXT NOT NULL,
    container_memory TEXT NOT NULL DEFAULT '2g',
    container_cpus   TEXT NOT NULL DEFAULT '2',
    created_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    status           TEXT NOT NULL DEFAULT 'active'
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_agents_name_unique ON agents(name);

CREATE TABLE IF NOT EXISTS messages (
    id          TEXT PRIMARY KEY,
    agent_id    TEXT NOT NULL REFERENCES agents(id),
    role        TEXT NOT NULL,
    content     TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    metadata    TEXT,
    status      TEXT NOT NULL DEFAULT 'complete',
    visibility  TEXT NOT NULL DEFAULT 'visible'
);
CREATE INDEX IF NOT EXISTS idx_messages_agent ON messages(agent_id, created_at);
CREATE INDEX IF NOT EXISTS idx_messages_agent_visibility ON messages(agent_id, visibility, created_at);

CREATE TABLE IF NOT EXISTS message_queue (
    id              TEXT PRIMARY KEY,
    agent_id        TEXT NOT NULL REFERENCES agents(id),
    payload         TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'QUEUED',
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    flushed_at      TEXT,
    processed_at    TEXT,
    agentic_task_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_message_queue_flush ON message_queue(agent_id, status, created_at);

CREATE TABLE IF NOT EXISTS agent_containers (
    id              TEXT PRIMARY KEY,
    agent_id        TEXT NOT NULL REFERENCES agents(id),
    container_id    TEXT,
    pid             INTEGER,
    container_type  TEXT NOT NULL DEFAULT 'session',
    status          TEXT NOT NULL DEFAULT 'starting',
    started_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    stopped_at      TEXT,
    last_activity   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    error_message   TEXT
);
CREATE INDEX IF NOT EXISTS idx_agent_containers_agent ON agent_containers(agent_id);
CREATE INDEX IF NOT EXISTS idx_agent_containers_status ON agent_containers(status);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
INSERT OR IGNORE INTO settings (key, value) VALUES ('ollama_enabled', 'true');
INSERT OR IGNORE INTO settings (key, value) VALUES ('slack_polling_enabled', 'false');
INSERT OR IGNORE INTO settings (key, value) VALUES ('session_history_window_size', '20');

CREATE TABLE IF NOT EXISTS scheduled_tasks (
    id              TEXT PRIMARY KEY,
    agent_id        TEXT NOT NULL REFERENCES agents(id),
    task_type       TEXT NOT NULL,
    payload         TEXT NOT NULL DEFAULT '{}',
    status          TEXT NOT NULL DEFAULT 'pending',
    scheduled_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    started_at      TEXT,
    completed_at    TEXT,
    result          TEXT,
    retry_count     INTEGER NOT NULL DEFAULT 0,
    max_retries     INTEGER NOT NULL DEFAULT 3,
    timeout_seconds INTEGER NOT NULL DEFAULT 300,
    error_message   TEXT,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_scheduled_tasks_status ON scheduled_tasks(status, scheduled_at);
CREATE INDEX IF NOT EXISTS idx_scheduled_tasks_agent ON scheduled_tasks(agent_id);

CREATE TABLE IF NOT EXISTS agentic_tasks (
    id               TEXT PRIMARY KEY,
    agent_id         TEXT NOT NULL REFERENCES agents(id),
    prompt           TEXT NOT NULL,
    allowed_tools    TEXT NOT NULL DEFAULT '[]',
    interval_seconds INTEGER NOT NULL,
    last_executed_at TEXT,
    last_result      TEXT,
    status           TEXT NOT NULL DEFAULT 'active',
    trigger_type     TEXT NOT NULL DEFAULT 'interval',
    trigger_config   TEXT NOT NULL DEFAULT '{}',
    trigger_secret   TEXT,
    created_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_agentic_tasks_status ON agentic_tasks(status);
CREATE INDEX IF NOT EXISTS idx_agentic_tasks_agent ON agentic_tasks(agent_id);

CREATE TABLE IF NOT EXISTS agent_skills (
    agent_id TEXT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    skill_id TEXT NOT NULL,
    enabled  INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (agent_id, skill_id)
);

CREATE TABLE IF NOT EXISTS slack_polling_channels (
    id               TEXT PRIMARY KEY,
    channel_id       TEXT NOT NULL UNIQUE,
    channel_name     TEXT NOT NULL DEFAULT '',
    interval_seconds INTEGER NOT NULL DEFAULT 30,
    last_ts          TEXT NOT NULL DEFAULT '0',
    enabled          INTEGER NOT NULL DEFAULT 1,
    created_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS slack_active_threads (
    id               TEXT PRIMARY KEY,
    channel_id       TEXT NOT NULL,
    thread_ts        TEXT NOT NULL,
    agent_id         TEXT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    last_ts          TEXT NOT NULL DEFAULT '0',
    last_activity_at TEXT NOT NULL DEFAULT '1970-01-01T00:00:00Z',
    created_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    UNIQUE (channel_id, thread_ts, agent_id)
);

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
