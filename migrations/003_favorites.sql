-- 003_favorites.sql

-- Allow 'favorites' task type in sync_tasks
ALTER TABLE sync_tasks DROP CONSTRAINT IF EXISTS sync_tasks_type_check;
ALTER TABLE sync_tasks ADD CONSTRAINT sync_tasks_type_check
    CHECK (type IN ('full', 'incremental', 'favorites'));

-- User favorites (behavior data, separate from gallery source data)
CREATE TABLE IF NOT EXISTS user_favorites (
    gid          BIGINT PRIMARY KEY REFERENCES eh_galleries(gid),
    favorited_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Preference tags (derived profile from favorites)
CREATE TABLE IF NOT EXISTS preference_tags (
    namespace    TEXT NOT NULL,   -- 'artist', 'group', 'character', 'parody'
    tag          TEXT NOT NULL,
    weight       REAL NOT NULL,   -- occurrence count in favorites
    PRIMARY KEY (namespace, tag)
);

-- Recommended cache (pre-computed recommendation scores)
CREATE TABLE IF NOT EXISTS recommended_cache (
    gid       BIGINT PRIMARY KEY REFERENCES eh_galleries(gid),
    rec_score REAL NOT NULL
);
