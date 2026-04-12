-- Add icon column for random emoji assigned at agent creation
ALTER TABLE agents ADD COLUMN icon TEXT NOT NULL DEFAULT '';
