-- 011_drop_sync_tasks.sql
-- River-backed workers now read/write sync_task_defs directly. The legacy
-- sync_tasks table and its companion columns on sync_task_defs are no longer
-- referenced and can be dropped.

ALTER TABLE sync_task_defs
    DROP COLUMN IF EXISTS legacy_type,
    DROP COLUMN IF EXISTS legacy_category;

DROP TABLE IF EXISTS sync_tasks;

-- sync_task_defs.id used to be backfilled from sync_tasks (SERIAL). Now that
-- sync_tasks is gone, give the def table its own sequence so admin INSERTs
-- without explicit id work.
CREATE SEQUENCE IF NOT EXISTS sync_task_defs_id_seq OWNED BY sync_task_defs.id;
SELECT setval('sync_task_defs_id_seq',
              GREATEST(COALESCE((SELECT MAX(id) FROM sync_task_defs), 0), 1));
ALTER TABLE sync_task_defs ALTER COLUMN id SET DEFAULT nextval('sync_task_defs_id_seq');
