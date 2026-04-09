-- Memory-based search indexes: session summaries from daily memory files.
-- Replaces per-message indexing (message_fts/message_vec) with per-session-summary
-- indexing for higher-signal, lower-noise retrieval.

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

-- Mapping table for vec0 rowid tracking.
-- vec0 doesn't support WHERE on auxiliary columns, so we track
-- chunk_key -> rowid to enable targeted deletion and updates.
CREATE TABLE IF NOT EXISTS memory_vec_map (
    chunk_key TEXT NOT NULL PRIMARY KEY,
    vec_rowid INTEGER NOT NULL
);
