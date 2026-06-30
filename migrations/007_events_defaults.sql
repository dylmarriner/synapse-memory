-- 007_events_defaults.sql — ensure the runtime-created events table has
-- proper defaults. The table is created in app/main.py with DEFAULT clauses
-- but earlier deployments were created before that, leaving id and
-- created_at without defaults. This migration back-fills them so the
-- RTK events endpoint works.

ALTER TABLE events ALTER COLUMN id         SET DEFAULT gen_random_uuid();
ALTER TABLE events ALTER COLUMN created_at SET DEFAULT NOW();
