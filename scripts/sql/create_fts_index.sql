-- OPTIONAL performance optimization. This creates an index only, not a new table.
-- For this learning corpus, PostgreSQL may still prefer a sequential scan.
-- Execute once when there are enough chunks to warrant indexing.
CREATE INDEX IF NOT EXISTS idx_chunks_fts_en
ON chunks USING GIN (to_tsvector('english', content));
