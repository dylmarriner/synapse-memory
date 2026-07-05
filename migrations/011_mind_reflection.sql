-- Migration 011: mind_reflection_log — audit trail for the Living Mind's
-- periodic self-reflection loop (distinct from mind_learning_events, which
-- tracks per-interaction learning, not unprompted reflection cycles).

CREATE TABLE IF NOT EXISTS mind_reflection_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    mind_id         UUID NOT NULL REFERENCES minds(id) ON DELETE CASCADE,
    topic           TEXT NOT NULL,
    stance          TEXT,
    strength        FLOAT,
    summary         TEXT,
    triggered_push  BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_mind_reflection_log_mind ON mind_reflection_log(mind_id, created_at DESC);
