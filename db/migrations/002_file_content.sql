-- Store full file text so the UI can show cited lines in context.
-- Run once on existing databases, then re-ingest your repos (ingest_repo.py ... --embed):
--   docker compose exec -T db psql -U devatlas -d devatlas < db/migrations/002_file_content.sql
ALTER TABLE files ADD COLUMN IF NOT EXISTS content TEXT;
