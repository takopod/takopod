-- Add github_enabled flag to agents table.

ALTER TABLE agents ADD COLUMN github_enabled INTEGER NOT NULL DEFAULT 0;
