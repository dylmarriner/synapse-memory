-- 009_code_context.sql — code-context layer (tree-sitter indexer, symbol
-- cards, blast radius, wiki). Mirrors the sdl-mcp / jcodemunch / codesight
-- model: each file is parsed into symbols; symbols have edges (calls,
-- imports, references); the index supports the Iris Gate Ladder of
-- progressive disclosure (metadata → signatures → hot path → full).

CREATE TABLE IF NOT EXISTS code_repos (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            TEXT NOT NULL,
    root_path       TEXT NOT NULL,
    agent_id        TEXT,
    metadata        JSONB NOT NULL DEFAULT '{}',
    last_indexed_at TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_code_repos_path ON code_repos(root_path);

-- Tracked source files (path, language, last mtime, byte size)
CREATE TABLE IF NOT EXISTS code_files (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    repo_id         UUID NOT NULL REFERENCES code_repos(id) ON DELETE CASCADE,
    path            TEXT NOT NULL,
    rel_path        TEXT NOT NULL,                -- path relative to repo root
    language        TEXT,                          -- python | javascript | typescript | go | rust | unknown
    bytes           INTEGER NOT NULL DEFAULT 0,
    line_count      INTEGER NOT NULL DEFAULT 0,
    mtime           TIMESTAMPTZ,
    content_hash    TEXT,                          -- sha256 of contents
    parsed          BOOLEAN NOT NULL DEFAULT FALSE,
    error           TEXT,
    indexed_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (repo_id, rel_path)
);
CREATE INDEX IF NOT EXISTS idx_code_files_repo ON code_files(repo_id);
CREATE INDEX IF NOT EXISTS idx_code_files_lang ON code_files(language);

-- Symbols extracted from files (functions, classes, methods, vars, types)
CREATE TABLE IF NOT EXISTS code_symbols (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    file_id         UUID NOT NULL REFERENCES code_files(id) ON DELETE CASCADE,
    repo_id         UUID NOT NULL REFERENCES code_repos(id) ON DELETE CASCADE,
    -- Identity
    name            TEXT NOT NULL,
    qualified_name  TEXT NOT NULL,                 -- e.g. "MyClass.method"
    kind            TEXT NOT NULL CHECK (kind IN ('function','method','class','variable','constant','interface','module','type','enum','property','macro')),
    -- Location (byte offsets into the original file)
    start_byte      INTEGER NOT NULL,
    end_byte        INTEGER NOT NULL,
    start_line      INTEGER NOT NULL,
    end_line        INTEGER NOT NULL,
    -- Signature / preview
    signature       TEXT,                          -- "def foo(x: int) -> str"
    docstring       TEXT,                          -- first-line summary
    return_type     TEXT,                          -- for typed langs
    parameters      JSONB NOT NULL DEFAULT '[]',   -- [{name, type, default}]
    -- Card / content
    summary         TEXT,                          -- one-line human summary
    source          TEXT,                          -- full source (lazy)
    -- Metadata
    parent_symbol_id UUID REFERENCES code_symbols(id) ON DELETE SET NULL,
    decorators      JSONB NOT NULL DEFAULT '[]',   -- ['@staticmethod', ...]
    visibility      TEXT,                          -- public | private | protected
    is_exported     BOOLEAN NOT NULL DEFAULT TRUE,
    is_async        BOOLEAN NOT NULL DEFAULT FALSE,
    complexity      INTEGER,                       -- cyclomatic complexity
    line_count      INTEGER,
    metadata        JSONB NOT NULL DEFAULT '{}',
    indexed_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_code_symbols_repo ON code_symbols(repo_id);
CREATE INDEX IF NOT EXISTS idx_code_symbols_file ON code_symbols(file_id);
CREATE INDEX IF NOT EXISTS idx_code_symbols_name ON code_symbols(name);
CREATE INDEX IF NOT EXISTS idx_code_symbols_qualified ON code_symbols(qualified_name);
CREATE INDEX IF NOT EXISTS idx_code_symbols_kind ON code_symbols(kind);
CREATE INDEX IF NOT EXISTS idx_code_symbols_parent ON code_symbols(parent_symbol_id);
-- For BM25-like search on symbol names (gin trigram)
CREATE INDEX IF NOT EXISTS idx_code_symbols_name_trgm ON code_symbols USING GIN (name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_code_symbols_qname_trgm ON code_symbols USING GIN (qualified_name gin_trgm_ops);

-- Edges: call, import, reference, implements, extends
CREATE TABLE IF NOT EXISTS code_edges (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    repo_id         UUID NOT NULL REFERENCES code_repos(id) ON DELETE CASCADE,
    src_symbol_id   UUID REFERENCES code_symbols(id) ON DELETE CASCADE,
    src_file_id     UUID NOT NULL REFERENCES code_files(id) ON DELETE CASCADE,
    -- Either a target symbol (intra-repo) or a raw reference (unresolved)
    dst_symbol_id   UUID REFERENCES code_symbols(id) ON DELETE CASCADE,
    dst_name        TEXT,                          -- raw unresolved name
    kind            TEXT NOT NULL CHECK (kind IN ('call','import','reference','implements','extends','uses','decorates','returns')),
    weight          REAL NOT NULL DEFAULT 1.0,
    confidence      REAL NOT NULL DEFAULT 0.5,    -- resolved? 0.0-1.0
    line            INTEGER,
    metadata        JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_code_edges_repo ON code_edges(repo_id);
CREATE INDEX IF NOT EXISTS idx_code_edges_src_symbol ON code_edges(src_symbol_id);
CREATE INDEX IF NOT EXISTS idx_code_edges_dst_symbol ON code_edges(dst_symbol_id);
CREATE INDEX IF NOT EXISTS idx_code_edges_dst_name ON code_edges(dst_name);
CREATE INDEX IF NOT EXISTS idx_code_edges_kind ON code_edges(kind);
CREATE INDEX IF NOT EXISTS idx_code_edges_file ON code_edges(src_file_id);

-- Wiki articles (per-topic knowledge chunks)
CREATE TABLE IF NOT EXISTS code_wiki_articles (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    repo_id         UUID NOT NULL REFERENCES code_repos(id) ON DELETE CASCADE,
    title           TEXT NOT NULL,
    slug            TEXT NOT NULL,                 -- e.g. "auth-flow"
    content         TEXT NOT NULL,                  -- markdown body
    section         TEXT,                           -- e.g. "routes", "models", "tests"
    token_estimate  INTEGER NOT NULL DEFAULT 0,
    source_symbol_ids JSONB NOT NULL DEFAULT '[]',
    generated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (repo_id, slug)
);
CREATE INDEX IF NOT EXISTS idx_code_wiki_repo ON code_wiki_articles(repo_id);
CREATE INDEX IF NOT EXISTS idx_code_wiki_section ON code_wiki_articles(section);

-- Indexer run history (for "last indexed at" + error tracking)
CREATE TABLE IF NOT EXISTS code_index_runs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    repo_id         UUID NOT NULL REFERENCES code_repos(id) ON DELETE CASCADE,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at     TIMESTAMPTZ,
    files_seen      INTEGER NOT NULL DEFAULT 0,
    files_indexed   INTEGER NOT NULL DEFAULT 0,
    files_errored   INTEGER NOT NULL DEFAULT 0,
    symbols         INTEGER NOT NULL DEFAULT 0,
    edges           INTEGER NOT NULL DEFAULT 0,
    duration_ms     INTEGER,
    trigger         TEXT,                          -- manual | watch | git_hook
    error           TEXT
);
CREATE INDEX IF NOT EXISTS idx_code_index_runs_repo ON code_index_runs(repo_id);

-- Iris Gate audit log: every time an agent escalates from a metadata
-- card to full source, we log it. The audit enables measuring token
-- savings and detecting overly-greedy agents.
CREATE TABLE IF NOT EXISTS code_iris_audit (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    repo_id         UUID NOT NULL REFERENCES code_repos(id) ON DELETE CASCADE,
    agent_id        TEXT,
    symbol_id       UUID REFERENCES code_symbols(id) ON DELETE SET NULL,
    rung            INTEGER NOT NULL CHECK (rung BETWEEN 1 AND 4),
    bytes_returned  INTEGER NOT NULL,
    justification   TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_code_iris_repo ON code_iris_audit(repo_id);
CREATE INDEX IF NOT EXISTS idx_code_iris_agent ON code_iris_audit(agent_id);

-- Default global repo for ad-hoc indexing
INSERT INTO code_repos (name, root_path, agent_id, metadata)
VALUES ('nexus-self', '/app', 'system', '{"description":"Nexus codebase indexed as a reference"}')
ON CONFLICT (root_path) DO NOTHING;
