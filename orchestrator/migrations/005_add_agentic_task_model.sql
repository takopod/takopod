-- Add model column to agentic_tasks for per-schedule model selection
ALTER TABLE agentic_tasks ADD COLUMN model TEXT;
