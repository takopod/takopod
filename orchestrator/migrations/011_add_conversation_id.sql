-- Add conversation_id to messages for per-conversation isolation.
-- NULL = web UI (backward compat), "slack:{channel}:{thread_ts}" = Slack thread.
ALTER TABLE messages ADD COLUMN conversation_id TEXT;
CREATE INDEX IF NOT EXISTS idx_messages_conversation
    ON messages(agent_id, conversation_id, created_at);
