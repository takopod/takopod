CREATE TABLE IF NOT EXISTS slack_active_threads (
    id         TEXT PRIMARY KEY,
    channel_id TEXT NOT NULL,
    thread_ts  TEXT NOT NULL,
    agent_id   TEXT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    last_ts    TEXT NOT NULL DEFAULT '0',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    UNIQUE (channel_id, thread_ts, agent_id)
);
