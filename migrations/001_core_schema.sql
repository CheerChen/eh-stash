-- 001_core_schema.sql
-- Core gallery source data, thumb fetch queue, version grouping.
-- This is the foundation that everything else attaches to.

CREATE TABLE IF NOT EXISTS eh_galleries (
    gid             BIGINT PRIMARY KEY,
    token           TEXT NOT NULL,
    category        TEXT,                        -- 'Manga' | 'Doujinshi' | 'Cosplay'
    title           TEXT,
    title_jpn       TEXT,
    base_title      TEXT,                        -- normalized title for version grouping (see backfill below)
    uploader        TEXT,
    posted_at       TIMESTAMPTZ,
    language        TEXT,
    pages           INT,
    rating          NUMERIC(3, 2),
    fav_count       INT DEFAULT 0,
    thumb           TEXT,                        -- cover CDN URL
    comment_count   INT DEFAULT 0,
    tags            JSONB,                       -- {"female": ["schoolgirl"], "language": ["chinese"]}
    last_synced_at  TIMESTAMPTZ,                 -- NULL = detail never fetched
    is_active       BOOLEAN DEFAULT TRUE         -- soft-delete flag
);

CREATE INDEX IF NOT EXISTS idx_eh_galleries_category   ON eh_galleries (category);
CREATE INDEX IF NOT EXISTS idx_eh_galleries_fav_count  ON eh_galleries (fav_count DESC);
CREATE INDEX IF NOT EXISTS idx_eh_galleries_rating     ON eh_galleries (rating DESC);
CREATE INDEX IF NOT EXISTS idx_eh_galleries_posted_at  ON eh_galleries (posted_at DESC);
CREATE INDEX IF NOT EXISTS idx_eh_galleries_language   ON eh_galleries (language);
CREATE INDEX IF NOT EXISTS idx_eh_galleries_tags       ON eh_galleries USING GIN (tags);
CREATE INDEX IF NOT EXISTS idx_eh_galleries_base_title ON eh_galleries (base_title)
    WHERE base_title IS NOT NULL AND base_title != '';

-- Idempotent base_title backfill for any rows already present without it
-- (prefer title_jpn, fallback to title; strip Chinese-translation tags and group markers).
UPDATE eh_galleries
SET base_title = REGEXP_REPLACE(
    REGEXP_REPLACE(
        COALESCE(NULLIF(title_jpn, ''), title),
        '\s*\[中国翻訳\]|\s*\[中国語\]|\s*\[DL版\]|\s*\[無修正\]|\s*\(C\d+\)', '', 'g'
    ),
    '\s+', '', 'g'
)
WHERE base_title IS NULL
  AND COALESCE(NULLIF(title_jpn, ''), title) IS NOT NULL;

-- Thumb fetch queue. Populated alongside gallery upserts, drained by the
-- thumb worker; status transitions: pending -> processing -> done | failed.
CREATE TABLE IF NOT EXISTS thumb_queue (
    id              SERIAL PRIMARY KEY,
    gid             BIGINT NOT NULL UNIQUE,
    thumb_url       TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'processing', 'done', 'failed')),
    retry_count     INT DEFAULT 0,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    processed_at    TIMESTAMPTZ,
    next_retry_at   TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_thumb_queue_pending
    ON thumb_queue (created_at) WHERE status = 'pending';

CREATE INDEX IF NOT EXISTS idx_thumb_queue_retry
    ON thumb_queue (next_retry_at) WHERE status = 'pending';

-- Gallery version grouping: groups galleries sharing the same base_title
-- (translations / DL editions / etc) under the oldest gid in the group.
CREATE TABLE IF NOT EXISTS gallery_group_members (
    group_id    BIGINT NOT NULL,                 -- oldest gid in the group
    gid         BIGINT NOT NULL REFERENCES eh_galleries(gid),
    UNIQUE(gid)
);

CREATE INDEX IF NOT EXISTS idx_ggm_group_id ON gallery_group_members(group_id);
