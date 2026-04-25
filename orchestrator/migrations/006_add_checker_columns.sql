-- Separate mutable polling state (cursor) from static trigger config,
-- and track when checkers last ran for observability.
ALTER TABLE agentic_tasks ADD COLUMN cursor TEXT NOT NULL DEFAULT '{}';
ALTER TABLE agentic_tasks ADD COLUMN last_checked_at TEXT;

-- Migrate existing file_watch tasks: move last_snapshot from trigger_config into cursor.
UPDATE agentic_tasks
SET cursor = json_object('snapshot', json_extract(trigger_config, '$.last_snapshot')),
    trigger_config = json_remove(trigger_config, '$.last_snapshot')
WHERE trigger_type = 'file_watch'
  AND json_extract(trigger_config, '$.last_snapshot') IS NOT NULL;
