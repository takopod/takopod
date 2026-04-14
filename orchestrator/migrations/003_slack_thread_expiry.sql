ALTER TABLE slack_active_threads
    ADD COLUMN last_activity_at TEXT NOT NULL DEFAULT '1970-01-01T00:00:00Z';

UPDATE slack_active_threads SET last_activity_at = created_at;
