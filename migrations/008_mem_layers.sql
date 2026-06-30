-- 008_mem_layers.sql — MemOS-style L1/L2/L3 layered memory + tree structure
--
-- L1 = ActivationMemory   (short-term, hot, fast decay; recent session context)
-- L2 = PreferenceMemory   (durable user prefs/skills; slow decay; survives restarts)
-- L3 = WorldModelMemory   (stable facts about the user/agent/project; no decay)
--
-- Plus:
--   memory_cubes  — per-user / per-project memory isolation
--   memory_links  — tree-text parent/child + cross-memory relations
--   image_memory  — multi-modal image support
--   skill_cards   — crystallized reusable patterns (L2+ tier)

-- ── Memory cubes (isolation + composition) ──────────────────────────────
CREATE TABLE IF NOT EXISTS memory_cubes (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            TEXT NOT NULL UNIQUE,
    owner_id        TEXT,
    scope           TEXT NOT NULL DEFAULT 'private',  -- private | shared | public
    metadata        JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_memory_cubes_owner ON memory_cubes(owner_id);
CREATE INDEX IF NOT EXISTS idx_memory_cubes_scope ON memory_cubes(scope);

-- ── Memory layers (L1/L2/L3) ────────────────────────────────────────────
-- The layer determines default decay, retrieval priority, and storage class.
-- L1: short-term, hot, default TTL 7d, high access decay
-- L2: medium-term, warm, default TTL 90d, low decay
-- L3: long-term, cold, no TTL, never auto-expires
CREATE TABLE IF NOT EXISTS memory_layers (
    memory_id       UUID PRIMARY KEY REFERENCES memories(id) ON DELETE CASCADE,
    layer           TEXT NOT NULL CHECK (layer IN ('L1', 'L2', 'L3')),
    cube_id         UUID REFERENCES memory_cubes(id) ON DELETE SET NULL,
    -- Layer-specific fields
    activation_score REAL NOT NULL DEFAULT 0.0,  -- current activation (0..1); L1
    pinned          BOOLEAN NOT NULL DEFAULT FALSE, -- true = never auto-decay
    -- L1-only: when this layer was last "touched" by access
    last_activated_at TIMESTAMPTZ,
    -- L2-only: confidence from the user (1.0 = explicit, 0.5 = inferred)
    user_confidence REAL NOT NULL DEFAULT 1.0,
    -- L3-only: how the world fact was verified (manual | observed | inferred)
    verification    TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_memory_layers_layer ON memory_layers(layer);
CREATE INDEX IF NOT EXISTS idx_memory_layers_cube ON memory_layers(cube_id);
CREATE INDEX IF NOT EXISTS idx_memory_layers_activation ON memory_layers(activation_score DESC);
CREATE INDEX IF NOT EXISTS idx_memory_layers_last_activated ON memory_layers(last_activated_at DESC);

-- ── Memory links (tree-text + cross-memory relations) ───────────────────
-- kind: parent_of | child_of | related | supersedes | derived_from | contradicts
-- The 'parent_of' edges form the tree; 'related' is a graph edge.
CREATE TABLE IF NOT EXISTS memory_links (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    src_id          UUID NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
    dst_id          UUID NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
    kind            TEXT NOT NULL CHECK (kind IN ('parent_of','child_of','related','supersedes','derived_from','contradicts')),
    weight          REAL NOT NULL DEFAULT 1.0,
    metadata        JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (src_id, dst_id, kind)
);
CREATE INDEX IF NOT EXISTS idx_memory_links_src ON memory_links(src_id);
CREATE INDEX IF NOT EXISTS idx_memory_links_dst ON memory_links(dst_id);
CREATE INDEX IF NOT EXISTS idx_memory_links_kind ON memory_links(kind);

-- ── Image memory (multi-modal) ──────────────────────────────────────────
-- Stores image references for memories. The actual image bytes live on
-- disk under /var/lib/nexus/images/<id>.<ext>; this row holds the URL,
-- mime, dimensions, and a perceptual hash for dedup.
CREATE TABLE IF NOT EXISTS image_memory (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    memory_id       UUID NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
    url             TEXT NOT NULL,                -- /v1/images/<id> or external
    storage_path    TEXT NOT NULL,                -- absolute path on disk
    mime_type       TEXT NOT NULL DEFAULT 'image/png',
    width           INTEGER,
    height          INTEGER,
    bytes           INTEGER,
    phash           TEXT,                          -- perceptual hash for dedup
    caption         TEXT,                          -- LLM-generated description
    ocr_text        TEXT,                          -- extracted text (OCR)
    metadata        JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_image_memory_memory ON image_memory(memory_id);
CREATE INDEX IF NOT EXISTS idx_image_memory_phash ON image_memory(phash);

-- ── Tool memory (agent tool-use history) ────────────────────────────────
-- Tracks what tools an agent called, with what args, and what came back.
-- Used to recall "last time you used curl --resolve..." patterns.
CREATE TABLE IF NOT EXISTS tool_memory (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id        TEXT NOT NULL,
    tool_name       TEXT NOT NULL,
    args_summary    TEXT,                          -- truncated args
    result_summary  TEXT,                          -- truncated result
    success         BOOLEAN NOT NULL DEFAULT TRUE,
    duration_ms     INTEGER,
    session_id      UUID,
    memory_id       UUID REFERENCES memories(id) ON DELETE SET NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_tool_memory_agent ON tool_memory(agent_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tool_memory_tool ON tool_memory(tool_name);
CREATE INDEX IF NOT EXISTS idx_tool_memory_session ON tool_memory(session_id);

-- ── Skill cards (crystallized reusable patterns) ────────────────────────
-- A skill is a memory the agent has used 3+ times successfully. Stored
-- at L2 with high importance. Use these to suggest "you have a skill
-- for this" when the agent is doing similar work.
CREATE TABLE IF NOT EXISTS skill_cards (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            TEXT NOT NULL UNIQUE,
    description     TEXT NOT NULL,
    trigger_pattern TEXT NOT NULL,                  -- regex / semantic pattern
    steps           JSONB NOT NULL DEFAULT '[]',   -- ordered steps to execute
    use_count       INTEGER NOT NULL DEFAULT 0,
    success_count   INTEGER NOT NULL DEFAULT 0,
    last_used_at    TIMESTAMPTZ,
    source_memory_ids JSONB NOT NULL DEFAULT '[]', -- memories that formed this skill
    agent_id        TEXT,
    metadata        JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_skill_cards_agent ON skill_cards(agent_id);
CREATE INDEX IF NOT EXISTS idx_skill_cards_use ON skill_cards(use_count DESC);

-- ── Memory feedback (natural-language corrections) ──────────────────────
-- A user can say "memory X is wrong, correct it to say Y". The feedback
-- record keeps the original + the correction, so we can audit and
-- rollback. Each feedback may or may not have a derived correction memory.
CREATE TABLE IF NOT EXISTS memory_feedback (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    target_memory_id UUID REFERENCES memories(id) ON DELETE SET NULL,
    agent_id        TEXT,
    feedback_kind   TEXT NOT NULL CHECK (feedback_kind IN ('correct','supplement','merge','delete','pin','demote')),
    original_text   TEXT,
    new_text        TEXT,
    merged_with_id  UUID REFERENCES memories(id) ON DELETE SET NULL,
    applied         BOOLEAN NOT NULL DEFAULT FALSE,
    applied_memory_id UUID REFERENCES memories(id) ON DELETE SET NULL,
    metadata        JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_memory_feedback_target ON memory_feedback(target_memory_id);
CREATE INDEX IF NOT EXISTS idx_memory_feedback_agent ON memory_feedback(agent_id);

-- ── L1 activation background decay ──────────────────────────────────────
-- A simple background job: every hour, multiply activation_score by 0.95
-- for L1 memories that haven't been accessed. When score drops below
-- 0.1, mark for compression (move content to L2 if it has been useful,
-- else delete).
--
-- (The actual decay loop is in app/memory/decay.py; this comment is
-- the schema-side reminder of the lifecycle.)

-- ── Default cube for 'global' memories ──────────────────────────────────
INSERT INTO memory_cubes (name, owner_id, scope, metadata)
VALUES ('global', 'default', 'shared', '{"description": "Default shared cube for all agents on the system"}')
ON CONFLICT (name) DO NOTHING;
