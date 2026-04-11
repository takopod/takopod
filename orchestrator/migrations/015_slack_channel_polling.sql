-- Re-add UNIQUE constraint on agents.name for Slack @-mention routing.
CREATE UNIQUE INDEX IF NOT EXISTS idx_agents_name_unique ON agents(name);

-- Global toggle for Slack channel polling.
INSERT OR IGNORE INTO settings (key, value) VALUES ('slack_polling_enabled', 'false');

-- Per-channel polling configuration.
CREATE TABLE IF NOT EXISTS slack_polling_channels (
    id               TEXT PRIMARY KEY,
    channel_id       TEXT NOT NULL UNIQUE,
    channel_name     TEXT NOT NULL DEFAULT '',
    interval_seconds INTEGER NOT NULL DEFAULT 30,
    last_ts          TEXT NOT NULL DEFAULT '0',
    enabled          INTEGER NOT NULL DEFAULT 1,
    created_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
