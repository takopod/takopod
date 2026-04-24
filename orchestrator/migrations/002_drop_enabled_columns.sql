-- Drop the `enabled` column from agent_skills and agent_mcp_servers.
-- Presence in the table now means "active"; absence means "removed".
-- SQLite lacks ALTER TABLE DROP COLUMN before 3.35, so recreate the tables.

-- Also delete rows that were disabled (enabled = 0) since they are no
-- longer meaningful — presence = active.

-- agent_skills
CREATE TABLE IF NOT EXISTS agent_skills_new (
    agent_id TEXT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    skill_id TEXT NOT NULL,
    PRIMARY KEY (agent_id, skill_id)
);
INSERT INTO agent_skills_new (agent_id, skill_id)
    SELECT agent_id, skill_id FROM agent_skills WHERE enabled = 1;
DROP TABLE IF EXISTS agent_skills;
ALTER TABLE agent_skills_new RENAME TO agent_skills;

-- agent_mcp_servers
CREATE TABLE IF NOT EXISTS agent_mcp_servers_new (
    agent_id      TEXT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    mcp_server_id TEXT NOT NULL REFERENCES mcp_servers(id) ON DELETE CASCADE,
    PRIMARY KEY (agent_id, mcp_server_id)
);
INSERT INTO agent_mcp_servers_new (agent_id, mcp_server_id)
    SELECT agent_id, mcp_server_id FROM agent_mcp_servers WHERE enabled = 1;
DROP TABLE IF EXISTS agent_mcp_servers;
ALTER TABLE agent_mcp_servers_new RENAME TO agent_mcp_servers;
