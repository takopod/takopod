ALTER TABLE agentic_tasks ADD COLUMN trigger_type TEXT NOT NULL DEFAULT 'interval';
ALTER TABLE agentic_tasks ADD COLUMN trigger_config TEXT NOT NULL DEFAULT '{}';
ALTER TABLE agentic_tasks ADD COLUMN trigger_secret TEXT;
