-- Add agent registry enhancements for multi-agent architectures
-- These fields help agents discover each other's capabilities and track activity

ALTER TABLE agents 
ADD COLUMN IF NOT EXISTS last_active TIMESTAMP WITH TIME ZONE,
ADD COLUMN IF NOT EXISTS session_count INTEGER DEFAULT 0,
ADD COLUMN IF NOT EXISTS model VARCHAR(100);

-- Create index for active agent discovery
CREATE INDEX IF NOT EXISTS idx_agents_last_active ON agents (last_active DESC);

-- Create index for model-based agent filtering
CREATE INDEX IF NOT EXISTS idx_agents_model ON agents (model);

-- Add comment to document the new fields
COMMENT ON COLUMN agents.last_active IS 'Timestamp of the last agent activity/session';
COMMENT ON COLUMN agents.session_count IS 'Number of sessions the agent has participated in';
COMMENT ON COLUMN agents.model IS 'AI model used by this agent (e.g., gpt-4, claude-3, etc.)';
