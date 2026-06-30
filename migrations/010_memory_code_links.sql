-- 010_memory_code_links.sql — connect memories to code symbols.
-- A memory can reference one or more code symbols (function names, classes,
-- paths).  The link captures WHY the memory is attached (manual annotation,
-- auto-extracted from memory content, or mind-injected during reasoning).

CREATE TABLE IF NOT EXISTS memory_code_links (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    memory_id       UUID NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
    code_repo_id    UUID NOT NULL REFERENCES code_repos(id) ON DELETE CASCADE,
    code_symbol_id  UUID REFERENCES code_symbols(id) ON DELETE CASCADE,
    -- Either a symbol (preferred) or a raw text reference (e.g. "the
    -- sync script" when no exact symbol matches).  Exactly one is set.
    code_file_id    UUID REFERENCES code_files(id) ON DELETE CASCADE,
    raw_text        TEXT,
    -- Why this link exists
    source          TEXT NOT NULL CHECK (source IN ('manual','auto_extract','mind_inject','user_feedback')) DEFAULT 'auto_extract',
    confidence      REAL NOT NULL DEFAULT 0.5,
    metadata        JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- Either code_symbol_id OR code_file_id OR raw_text must be set
    CHECK (
        (code_symbol_id IS NOT NULL)::int
      + (code_file_id IS NOT NULL)::int
      + (raw_text IS NOT NULL)::int
      >= 1
    )
);
CREATE INDEX IF NOT EXISTS idx_memory_code_links_memory ON memory_code_links(memory_id);
CREATE INDEX IF NOT EXISTS idx_memory_code_links_symbol ON memory_code_links(code_symbol_id);
CREATE INDEX IF NOT EXISTS idx_memory_code_links_file ON memory_code_links(code_file_id);
CREATE INDEX IF NOT EXISTS idx_memory_code_links_repo ON memory_code_links(code_repo_id);
CREATE INDEX IF NOT EXISTS idx_memory_code_links_source ON memory_code_links(source);
