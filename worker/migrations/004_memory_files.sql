CREATE TABLE IF NOT EXISTS memory_files (
    id          TEXT PRIMARY KEY,
    date        TEXT NOT NULL,
    file_path   TEXT NOT NULL UNIQUE,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_memory_files_date ON memory_files(date);
