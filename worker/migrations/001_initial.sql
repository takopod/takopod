-- Consolidated schema: processed_messages, worker_responses, memory tables.

CREATE TABLE IF NOT EXISTS processed_messages (
    message_id  TEXT PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS worker_responses (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id TEXT NOT NULL,
    event      TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now'))
);
CREATE INDEX IF NOT EXISTS idx_worker_responses_status ON worker_responses(status, id);

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
