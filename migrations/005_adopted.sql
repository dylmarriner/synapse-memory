-- Migration 005: Adopted patterns — new tables and columns
-- All changes are additive; existing data is preserved.
-- New tables are CREATE IF NOT EXISTS; new columns are ALTER TABLE ADD IF NOT EXISTS.

-- ---------------------------------------------------------------------------
-- 1. memory_blocks — in-context named blocks (per-agent)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS memory_blocks (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id     UUID REFERENCES agents(id) ON DELETE CASCADE,
    label        TEXT NOT NULL,
    value        TEXT NOT NULL DEFAULT '',
    description  TEXT NOT NULL DEFAULT '',
    block_limit  INT NOT NULL DEFAULT 2000,
    read_only    BOOLEAN NOT NULL DEFAULT FALSE,
    hidden       BOOLEAN NOT NULL DEFAULT FALSE,
    metadata     JSONB NOT NULL DEFAULT '{}',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(agent_id, label)
);
CREATE INDEX IF NOT EXISTS idx_blocks_agent ON memory_blocks(agent_id);

-- ---------------------------------------------------------------------------
-- 2. Add tier / strength / scope columns to memories
-- ---------------------------------------------------------------------------
ALTER TABLE memories
    ADD COLUMN IF NOT EXISTS tier           TEXT NOT NULL DEFAULT 'working',
    ADD COLUMN IF NOT EXISTS strength       FLOAT NOT NULL DEFAULT 0.5,
    ADD COLUMN IF NOT EXISTS stability      FLOAT NOT NULL DEFAULT 30.0,
    ADD COLUMN IF NOT EXISTS last_activated TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS scope          TEXT,
    ADD COLUMN IF NOT EXISTS container_tag  TEXT,
    ADD COLUMN IF NOT EXISTS expiration_date DATE;

CREATE INDEX IF NOT EXISTS idx_memories_tier
    ON memories(agent_id, tier, importance DESC, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_memories_container
    ON memories(container_tag, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_memories_scope
    ON memories(scope) WHERE scope IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_memories_expiration
    ON memories(expiration_date) WHERE expiration_date IS NOT NULL;

-- ---------------------------------------------------------------------------
-- 3. peers — first-class participant records (human / agent / system)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS peers (
    id          TEXT NOT NULL,
    workspace   TEXT NOT NULL DEFAULT 'default',
    name        TEXT NOT NULL,
    kind        TEXT NOT NULL DEFAULT 'agent',  -- human | agent | system | external
    metadata    JSONB NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_active TIMESTAMPTZ,
    PRIMARY KEY (workspace, id)
);
CREATE INDEX IF NOT EXISTS idx_peers_workspace ON peers(workspace, kind);

-- ---------------------------------------------------------------------------
-- 4. peer_observations — (observer, observed) fact records
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS peer_observations (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace     TEXT NOT NULL DEFAULT 'default',
    observer      TEXT NOT NULL,
    observed      TEXT NOT NULL,
    text          TEXT NOT NULL,
    confidence    FLOAT NOT NULL DEFAULT 1.0,
    session       TEXT,
    memory_id     UUID REFERENCES memories(id) ON DELETE SET NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata      JSONB NOT NULL DEFAULT '{}',
    UNIQUE (workspace, observer, observed, text)
);
CREATE INDEX IF NOT EXISTS idx_peer_obs_observed ON peer_observations(workspace, observed, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_peer_obs_observer ON peer_observations(workspace, observer, created_at DESC);

-- ---------------------------------------------------------------------------
-- 5. temporal_triples — subject-predicate-object with validity windows
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS temporal_triples (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    subject      TEXT NOT NULL,
    predicate    TEXT NOT NULL,
    object       TEXT NOT NULL,
    valid_from   TIMESTAMPTZ,
    valid_to     TIMESTAMPTZ,
    confidence   FLOAT NOT NULL DEFAULT 1.0,
    source       TEXT,
    memory_id    UUID REFERENCES memories(id) ON DELETE SET NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_triples_subject ON temporal_triples(subject, valid_from, valid_to);
CREATE INDEX IF NOT EXISTS idx_triples_object  ON temporal_triples(object, valid_from, valid_to);
CREATE INDEX IF NOT EXISTS idx_triples_window  ON temporal_triples(valid_from, valid_to) WHERE valid_to IS NOT NULL;

-- ---------------------------------------------------------------------------
-- 6. hook_events — the 12 lifecycle events captured from agents
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS hook_events (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event        TEXT NOT NULL,
    session_id   TEXT,
    agent_id     TEXT,
    cwd          TEXT,
    data         JSONB NOT NULL DEFAULT '{}',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_hook_events_session ON hook_events(session_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_hook_events_agent   ON hook_events(agent_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_hook_events_event   ON hook_events(event, created_at DESC);

-- ---------------------------------------------------------------------------
-- 7. closets — verbatim topic pointers
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS closets (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    container_tag TEXT NOT NULL,
    text         TEXT NOT NULL,
    drawer_refs  TEXT[] NOT NULL DEFAULT '{}',
    metadata     JSONB NOT NULL DEFAULT '{}',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_closets_container ON closets(container_tag, created_at DESC);
