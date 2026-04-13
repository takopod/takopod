-- Drop unused per-message search tables, superseded by memory-based
-- search (memory_fts / memory_vec) in migration 005.
DROP TABLE IF EXISTS message_fts;
DROP TABLE IF EXISTS message_vec;
