
-- Switch to 384-dim vectors for bge-small-en-v1.5 local embeddings
ALTER TABLE memories ALTER COLUMN embedding TYPE vector(384);

-- Rebuild the HNSW index (it gets dropped on ALTER COLUMN TYPE)
DROP INDEX IF EXISTS idx_memories_embedding;
CREATE INDEX IF NOT EXISTS idx_memories_embedding ON memories 
    USING hnsw (embedding vector_cosine_ops) WITH (m=16, ef_construction=200);
