CREATE TABLE IF NOT EXISTS facts (
    id          TEXT PRIMARY KEY,
    key         TEXT NOT NULL,
    value       TEXT NOT NULL,
    category    TEXT NOT NULL DEFAULT 'general',
    source      TEXT,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    superseded  INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_facts_key ON facts(key);
CREATE INDEX IF NOT EXISTS idx_facts_category ON facts(category);
CREATE INDEX IF NOT EXISTS idx_facts_active ON facts(superseded) WHERE superseded = 0;
