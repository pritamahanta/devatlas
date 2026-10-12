-- Make full-text search identifier-aware.
-- Postgres' parser keeps "foo.bar" and "path/to/file" as single tokens; replacing
-- '.', '_' and '/' with spaces first lets queries match the parts (snake_case,
-- dotted names, paths). Run once on databases created before this change:
--   docker compose exec -T db psql -U devatlas -d devatlas < db/migrations/001_tsv_tokenization.sql
BEGIN;
DROP INDEX IF EXISTS chunks_tsv_idx;
ALTER TABLE chunks DROP COLUMN tsv;
ALTER TABLE chunks ADD COLUMN tsv tsvector GENERATED ALWAYS AS (
    to_tsvector('simple',
        regexp_replace(coalesce(symbol,'') || ' ' || content, '[._/]', ' ', 'g'))
) STORED;
CREATE INDEX chunks_tsv_idx ON chunks USING GIN (tsv);
COMMIT;
