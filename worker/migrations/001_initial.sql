-- Consolidated schema: processed_messages, memory tables, facts.

CREATE TABLE IF NOT EXISTS processed_messages (
    message_id  TEXT PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS memory_files (
    id          TEXT PRIMARY KEY,
    date        TEXT NOT NULL,
    file_path   TEXT NOT NULL UNIQUE,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_memory_files_date ON memory_files(date);

CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
    content,
    file_path UNINDEXED,
    chunk_key UNINDEXED,
    session_ref UNINDEXED,
    created_at UNINDEXED,
    tokenize = 'porter'
);

CREATE VIRTUAL TABLE IF NOT EXISTS memory_vec USING vec0(
    embedding float[768],
    +content TEXT,
    +file_path TEXT,
    +chunk_key TEXT,
    +session_ref TEXT,
    +created_at TEXT
);

CREATE TABLE IF NOT EXISTS memory_vec_map (
    chunk_key TEXT NOT NULL PRIMARY KEY,
    vec_rowid INTEGER NOT NULL
);

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
