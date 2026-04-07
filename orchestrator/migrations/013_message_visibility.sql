-- Add visibility column for soft-hide/delete support.
-- Values: 'visible' (default), 'hidden' (after Clear Context), 'deleted' (future use).
ALTER TABLE messages ADD COLUMN visibility TEXT NOT NULL DEFAULT 'visible';

CREATE INDEX IF NOT EXISTS idx_messages_visibility
    ON messages(session_id, visibility, created_at);
