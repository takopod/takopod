-- Add configurable model to agents (defaults to SDK default when NULL).
ALTER TABLE agents ADD COLUMN model TEXT;
