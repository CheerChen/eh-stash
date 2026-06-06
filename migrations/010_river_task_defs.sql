-- 010_river_task_defs.sql
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

    -- Legacy execution adapter. Kept only while workers still reuse sync_tasks
    -- as scratch state during the gradual migration.
    legacy_type           TEXT NOT NULL CHECK (legacy_type IN ('full', 'incremental', 'favorites')),
    legacy_category       TEXT NOT NULL,

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

-- One-time/idempotent backfill from the legacy sync_tasks table. This preserves
-- old offsets in checkpoint so River workers can resume from the same cursor.
INSERT INTO sync_task_defs (
    id, name, task_kind, source, strategy, scope, legacy_type, legacy_category,
    enabled, config, checkpoint, progress, schedule_kind, schedule_interval_sec,
    last_run_at, last_error, created_at, updated_at
)
SELECT
    id,
    name,
    CASE WHEN type = 'favorites' THEN 'favorites_sync' ELSE 'gallery_sync' END,
    CASE WHEN type = 'favorites' THEN 'favorites' ELSE 'gallery_list' END,
    CASE WHEN type = 'incremental' THEN 'incremental' ELSE 'full' END,
    CASE
        WHEN type = 'incremental' THEN jsonb_build_object('categories', COALESCE(config->'categories', '[]'::jsonb))
        WHEN type = 'favorites' THEN jsonb_build_object('target', 'user_favorites')
        ELSE jsonb_build_object('category', category)
    END,
    type,
    category,
    desired_status = 'running',
    config,
    state,
    jsonb_build_object(
        'pct', COALESCE(progress_pct, 0),
        'legacy_status', status,
        'legacy_desired_status', desired_status
    ),
    CASE WHEN type IN ('favorites', 'incremental') THEN 'periodic' ELSE 'manual' END,
    CASE
        WHEN type = 'favorites' THEN GREATEST(1, COALESCE((config->>'run_interval_hours')::DOUBLE PRECISION, 6))::INTEGER * 3600
        WHEN type = 'incremental' THEN 30
        ELSE NULL
    END,
    last_run_at,
    NULLIF(error_message, ''),
    created_at,
    updated_at
FROM sync_tasks
ON CONFLICT (id) DO UPDATE SET
    name = EXCLUDED.name,
    task_kind = EXCLUDED.task_kind,
    source = EXCLUDED.source,
    strategy = EXCLUDED.strategy,
    scope = EXCLUDED.scope,
    legacy_type = EXCLUDED.legacy_type,
    legacy_category = EXCLUDED.legacy_category,
    config = EXCLUDED.config,
    checkpoint = EXCLUDED.checkpoint,
    progress = EXCLUDED.progress,
    schedule_kind = EXCLUDED.schedule_kind,
    schedule_interval_sec = EXCLUDED.schedule_interval_sec,
    last_run_at = EXCLUDED.last_run_at,
    last_error = EXCLUDED.last_error,
    updated_at = NOW();
