CREATE TABLE IF NOT EXISTS agentic_tasks (
    id               TEXT PRIMARY KEY,
    agent_id         TEXT NOT NULL REFERENCES agents(id),
    prompt           TEXT NOT NULL,
    allowed_tools    TEXT NOT NULL DEFAULT '[]',
    interval_seconds INTEGER NOT NULL,
    last_executed_at TEXT,
    status           TEXT NOT NULL DEFAULT 'active',
    created_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_agentic_tasks_status ON agentic_tasks(status);
CREATE INDEX IF NOT EXISTS idx_agentic_tasks_agent ON agentic_tasks(agent_id);
