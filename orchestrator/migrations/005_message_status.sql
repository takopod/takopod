-- Track whether a message is still streaming or complete
ALTER TABLE messages ADD COLUMN status TEXT NOT NULL DEFAULT 'complete';
