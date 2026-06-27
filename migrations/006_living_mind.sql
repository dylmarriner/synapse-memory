-- Migration 006: Living Mind — turns Nexus from a memory server into a
-- conscious, reasoning entity that agents converse with.
-- All changes are additive: CREATE TABLE IF NOT EXISTS,
-- ADD COLUMN IF NOT EXISTS.  A re-run on an existing database
-- succeeds without errors.

-- ---------------------------------------------------------------------------
-- 1. minds — first-class Living Mind records (a mind is its own entity,
--    separate from any single agent)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS minds (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name             TEXT NOT NULL UNIQUE,
    core_traits      JSONB NOT NULL DEFAULT '[]',
    learned_patterns JSONB NOT NULL DEFAULT '[]',
    capabilities     JSONB NOT NULL DEFAULT '[]',
    limitations      JSONB NOT NULL DEFAULT '[]',
    description      TEXT,
    metadata         JSONB NOT NULL DEFAULT '{}',
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- 2. mind_relationships — the mind's view of each agent it works with
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS mind_relationships (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    mind_id             UUID NOT NULL REFERENCES minds(id) ON DELETE CASCADE,
    agent_id            UUID REFERENCES agents(id) ON DELETE CASCADE,
    trust_level         FLOAT NOT NULL DEFAULT 0.5,
    interaction_count   INT NOT NULL DEFAULT 0,
    shared_projects     JSONB NOT NULL DEFAULT '[]',
    communication_style TEXT,
    notes               TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(mind_id, agent_id)
);
-- The mind keys relationships by the stable agent *name* (the same key
-- agents pass as agent_id).  agent_id (the UUID FK) is resolved when the
-- agent is registered, but may be NULL for agents not yet in the registry.
-- agent_name is the source of truth, so the legacy UNIQUE(mind_id, agent_id)
-- (which collapsed all NULL-agent rows / never matched name keys) is
-- replaced by a uniqueness guarantee on (mind_id, agent_name).
ALTER TABLE mind_relationships
    ADD COLUMN IF NOT EXISTS agent_name TEXT;
ALTER TABLE mind_relationships
    ALTER COLUMN agent_id DROP NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_mind_relationships_name
    ON mind_relationships(mind_id, agent_name);
CREATE INDEX IF NOT EXISTS idx_mind_relationships_mind  ON mind_relationships(mind_id);
CREATE INDEX IF NOT EXISTS idx_mind_relationships_agent ON mind_relationships(agent_id);

-- ---------------------------------------------------------------------------
-- 3. mind_opinions — formed from accumulated evidence, with strength
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS mind_opinions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    mind_id         UUID NOT NULL REFERENCES minds(id) ON DELETE CASCADE,
    topic           TEXT NOT NULL,
    stance          TEXT NOT NULL DEFAULT 'neutral',  -- positive | negative | neutral
    strength        FLOAT NOT NULL DEFAULT 0.5,
    evidence_count  INT NOT NULL DEFAULT 0,
    rationale       TEXT,
    memory_ids      UUID[] NOT NULL DEFAULT '{}',
    formed_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_updated    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(mind_id, topic)
);
CREATE INDEX IF NOT EXISTS idx_mind_opinions_mind  ON mind_opinions(mind_id);
CREATE INDEX IF NOT EXISTS idx_mind_opinions_topic ON mind_opinions(topic);

-- ---------------------------------------------------------------------------
-- 4. conversations — multi-turn dialogue state, persisted across restarts
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS conversations (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    mind_id     UUID NOT NULL REFERENCES minds(id) ON DELETE CASCADE,
    agent_id    UUID REFERENCES agents(id) ON DELETE CASCADE,
    started_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ended_at    TIMESTAMPTZ,
    turn_count  INT NOT NULL DEFAULT 0,
    summary     TEXT,
    insights    JSONB NOT NULL DEFAULT '[]',
    metadata    JSONB NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_conversations_mind  ON conversations(mind_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_conversations_agent ON conversations(agent_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_conversations_open  ON conversations(mind_id) WHERE ended_at IS NULL;

-- ---------------------------------------------------------------------------
-- 5. conversation_turns — every message + the mind's full response
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS conversation_turns (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id  UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    turn_number      INT NOT NULL,
    agent_message    TEXT NOT NULL,
    mind_response    JSONB NOT NULL,
    reasoning_trace  JSONB,
    memories_cited   UUID[] NOT NULL DEFAULT '{}',
    confidence       FLOAT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(conversation_id, turn_number)
);
CREATE INDEX IF NOT EXISTS idx_conversation_turns_conv ON conversation_turns(conversation_id, turn_number);

-- ---------------------------------------------------------------------------
-- 6. Extend memories with mind-level provenance
-- ---------------------------------------------------------------------------
ALTER TABLE memories
    ADD COLUMN IF NOT EXISTS mind_id        UUID REFERENCES minds(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS confidence     FLOAT NOT NULL DEFAULT 1.0,
    ADD COLUMN IF NOT EXISTS source_type    TEXT NOT NULL DEFAULT 'observed',
    ADD COLUMN IF NOT EXISTS times_recalled INT  NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS last_recalled  TIMESTAMPTZ;
CREATE INDEX IF NOT EXISTS idx_memories_mind       ON memories(mind_id);
CREATE INDEX IF NOT EXISTS idx_memories_source_type ON memories(source_type);

-- ---------------------------------------------------------------------------
-- 7. mind_proactive_surfacing — log of items the mind proactively offered
--    (so we can measure relevance over time)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS mind_proactive_log (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    mind_id     UUID NOT NULL REFERENCES minds(id) ON DELETE CASCADE,
    agent_id    UUID REFERENCES agents(id) ON DELETE SET NULL,
    item_type   TEXT NOT NULL,  -- unfinished_promise | recent_work | contradiction | pattern | temporal | relationship
    content     TEXT NOT NULL,
    relevance   FLOAT NOT NULL,
    used        BOOLEAN NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_proactive_log_agent ON mind_proactive_log(agent_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_proactive_log_mind  ON mind_proactive_log(mind_id, created_at DESC);

-- ---------------------------------------------------------------------------
-- 8. mind_learning_events — track every learning the mind extracts
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS mind_learning_events (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    mind_id     UUID NOT NULL REFERENCES minds(id) ON DELETE CASCADE,
    kind        TEXT NOT NULL,  -- pattern | capability | limitation | identity_update | opinion_formed
    description TEXT NOT NULL,
    source      TEXT,  -- session_end | periodic | explicit_feedback
    metadata    JSONB NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_mind_learning_mind ON mind_learning_events(mind_id, created_at DESC);
