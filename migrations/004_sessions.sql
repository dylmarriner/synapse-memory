-- Phase 1 raw session/event memory archive and provenance links.

CREATE TABLE IF NOT EXISTS sessions (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id    UUID REFERENCES agents(id) ON DELETE SET NULL,
    agent_name  TEXT NOT NULL,
    project_key TEXT,
    title       TEXT,
    started_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ended_at    TIMESTAMPTZ,
    metadata    JSONB NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS messages (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id     UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role           TEXT NOT NULL,
    content        TEXT NOT NULL,
    token_estimate INT NOT NULL DEFAULT 0,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata       JSONB NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS memory_sources (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    memory_id   UUID NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
    source_kind TEXT NOT NULL,
    source_id   UUID NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata    JSONB NOT NULL DEFAULT '{}',
    UNIQUE(memory_id, source_kind, source_id)
);

CREATE INDEX IF NOT EXISTS idx_sessions_agent ON sessions(agent_name, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_sessions_project ON sessions(project_key, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_messages_session_time ON messages(session_id, created_at ASC);
CREATE INDEX IF NOT EXISTS idx_memory_sources_memory ON memory_sources(memory_id);
CREATE INDEX IF NOT EXISTS idx_memory_sources_source ON memory_sources(source_kind, source_id);
