-- Nexus unified memory schema
-- Run automatically on first postgres start.

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE IF NOT EXISTS agents (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT NOT NULL UNIQUE,
    metadata    JSONB NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    representation   TEXT,
    represented_at   TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS memories (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id         UUID REFERENCES agents(id) ON DELETE CASCADE,
    content          TEXT NOT NULL,
    memory_type      TEXT NOT NULL DEFAULT 'observation',
    embedding        vector(384),
    importance       FLOAT NOT NULL DEFAULT 0.5,
    access_count     INT NOT NULL DEFAULT 0,
    confirmed_count  INT NOT NULL DEFAULT 0,
    contradicted_count INT NOT NULL DEFAULT 0,
    accessed_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata         JSONB NOT NULL DEFAULT '{}',
    version          INT NOT NULL DEFAULT 1,
    superseded_by    UUID REFERENCES memories(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS entities (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT NOT NULL,
    entity_type TEXT,
    agent_id    UUID REFERENCES agents(id) ON DELETE CASCADE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(name, agent_id)
);

CREATE TABLE IF NOT EXISTS relations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    from_entity_id  UUID NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    to_entity_id    UUID NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    relation_type   TEXT NOT NULL,
    memory_id       UUID REFERENCES memories(id) ON DELETE SET NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS conclusions (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id         UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    content          TEXT NOT NULL,
    conclusion_type  TEXT NOT NULL DEFAULT 'derived',
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS summaries (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id     UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    content      TEXT NOT NULL,
    memory_count INT NOT NULL DEFAULT 0,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Performance indexes
CREATE INDEX IF NOT EXISTS idx_memories_agent       ON memories(agent_id);
CREATE INDEX IF NOT EXISTS idx_memories_type        ON memories(memory_type);
CREATE INDEX IF NOT EXISTS idx_memories_created     ON memories(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_memories_importance  ON memories(importance DESC);
CREATE INDEX IF NOT EXISTS idx_memories_accessed    ON memories(accessed_at DESC);
CREATE INDEX IF NOT EXISTS idx_memories_embedding   ON memories USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);
CREATE INDEX IF NOT EXISTS idx_memories_fts         ON memories USING gin(to_tsvector('english', content));
CREATE INDEX IF NOT EXISTS idx_entities_agent       ON entities(agent_id);
CREATE INDEX IF NOT EXISTS idx_entities_name        ON entities USING gin(name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_conclusions_agent    ON conclusions(agent_id);
CREATE INDEX IF NOT EXISTS idx_relations_from       ON relations(from_entity_id);
CREATE INDEX IF NOT EXISTS idx_relations_to         ON relations(to_entity_id);

CREATE INDEX IF NOT EXISTS idx_memories_tags_gin ON memories USING gin ((metadata->'tags'));
CREATE INDEX IF NOT EXISTS idx_memories_type_priority ON memories(memory_type, importance DESC, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_summaries_agent ON summaries(agent_id);
CREATE INDEX IF NOT EXISTS idx_summaries_agent_time ON summaries(agent_id, created_at DESC);
