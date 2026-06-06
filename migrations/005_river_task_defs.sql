-- 005_river_task_defs.sql
-- River-backed task definitions. River owns job execution state in river_job;
-- this table owns ehstash task configuration, scheduling intent, and offsets.

CREATE TABLE IF NOT EXISTS sync_task_defs (
    id                    INTEGER PRIMARY KEY,
    name                  TEXT NOT NULL UNIQUE,

    -- What this definition does, independent of how/when it runs.
    task_kind             TEXT NOT NULL CHECK (task_kind IN ('gallery_sync', 'favorites_sync')),
    source                TEXT NOT NULL CHECK (source IN ('gallery_list', 'favorites')),
    strategy              TEXT NOT NULL CHECK (strategy IN ('full', 'incremental')),
    scope                 JSONB NOT NULL DEFAULT '{}',

    enabled               BOOLEAN NOT NULL DEFAULT FALSE,
    config                JSONB NOT NULL DEFAULT '{}',
    checkpoint            JSONB NOT NULL DEFAULT '{}',
    progress              JSONB NOT NULL DEFAULT '{}',

    current_job_id        BIGINT,
    last_job_id           BIGINT,

    schedule_kind         TEXT NOT NULL DEFAULT 'manual'
                          CHECK (schedule_kind IN ('manual', 'periodic')),
    schedule_interval_sec INTEGER,
    next_run_at           TIMESTAMPTZ,
    last_run_at           TIMESTAMPTZ,
    last_finished_at      TIMESTAMPTZ,

    requested_action      TEXT
                          CHECK (requested_action IS NULL OR requested_action IN ('start', 'stop', 'retry')),
    requested_at          TIMESTAMPTZ,
    last_error            TEXT,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sync_task_defs_kind
    ON sync_task_defs (task_kind, source, strategy);

CREATE INDEX IF NOT EXISTS idx_sync_task_defs_requested_action
    ON sync_task_defs (requested_action)
    WHERE requested_action IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_sync_task_defs_current_job
    ON sync_task_defs (current_job_id)
    WHERE current_job_id IS NOT NULL;

-- Auto-assign id for admin INSERTs that don't specify one.
CREATE SEQUENCE IF NOT EXISTS sync_task_defs_id_seq OWNED BY sync_task_defs.id;
SELECT setval('sync_task_defs_id_seq',
              GREATEST(COALESCE((SELECT MAX(id) FROM sync_task_defs), 0), 1));
ALTER TABLE sync_task_defs ALTER COLUMN id SET DEFAULT nextval('sync_task_defs_id_seq');

-- Lifecycle/audit log for each task definition. River workers append events
-- here on round start, completion, retry, etc.
CREATE TABLE IF NOT EXISTS sync_task_events (
    id          BIGSERIAL PRIMARY KEY,
    task_id     INTEGER REFERENCES sync_task_defs(id) ON DELETE CASCADE,
    job_id      BIGINT,
    event_type  TEXT NOT NULL,
    message     TEXT,
    payload     JSONB NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sync_task_events_created
    ON sync_task_events (created_at, id);
