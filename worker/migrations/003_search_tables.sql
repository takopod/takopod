CREATE VIRTUAL TABLE IF NOT EXISTS message_fts USING fts5(
    content,
    role,
    session_id UNINDEXED,
    message_id UNINDEXED,
    created_at UNINDEXED,
    tokenize = 'porter'
);

CREATE VIRTUAL TABLE IF NOT EXISTS message_vec USING vec0(
    embedding float[768],
    +content TEXT,
    +role TEXT,
    +session_id TEXT,
    +message_id TEXT,
    +created_at TEXT
);
