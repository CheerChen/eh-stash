-- 001_schema.sql

CREATE TABLE IF NOT EXISTS eh_galleries (
    gid             BIGINT PRIMARY KEY,
    token           TEXT NOT NULL,
    category        TEXT,                        -- 'Manga' | 'Doujinshi' | 'Cosplay'
    title           TEXT,
    title_jpn       TEXT,
    uploader        TEXT,
    posted_at       TIMESTAMPTZ,
    language        TEXT,
    pages           INT,
    rating          NUMERIC(3, 2),
    fav_count       INT DEFAULT 0,
    thumb           TEXT,                        -- 封面 CDN URL
    comment_count   INT DEFAULT 0,               -- 评论数
    tags            JSONB,                       -- {"female": ["schoolgirl"], "language": ["chinese"]}
    last_synced_at  TIMESTAMPTZ,                 -- NULL = 从未抓过 detail；非 NULL = 最后同步时间
    is_active       BOOLEAN DEFAULT TRUE         -- 软删除（画廊被删时标记 false）
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_eh_galleries_category      ON eh_galleries (category);
CREATE INDEX IF NOT EXISTS idx_eh_galleries_fav_count     ON eh_galleries (fav_count DESC);
CREATE INDEX IF NOT EXISTS idx_eh_galleries_rating        ON eh_galleries (rating DESC);
CREATE INDEX IF NOT EXISTS idx_eh_galleries_posted_at     ON eh_galleries (posted_at DESC);
CREATE INDEX IF NOT EXISTS idx_eh_galleries_language      ON eh_galleries (language);
CREATE INDEX IF NOT EXISTS idx_eh_galleries_tags          ON eh_galleries USING GIN (tags);

CREATE TABLE IF NOT EXISTS schedule_state (
    job_name    TEXT PRIMARY KEY,
    state       JSONB,
    last_run_at TIMESTAMPTZ
);

-- 预置任务行
INSERT INTO schedule_state (job_name, state) VALUES
    ('scraper-manga',     '{"next_gid": null, "round": 0}'),
    ('scraper-doujinshi', '{"next_gid": null, "round": 0}'),
    ('scraper-cosplay',   '{"next_gid": null, "round": 0}'),
    ('callback-manga',    '{"next_gid": null, "round": 0}'),
    ('callback-doujinshi','{"next_gid": null, "round": 0}'),
    ('callback-cosplay',  '{"next_gid": null, "round": 0}')
ON CONFLICT (job_name) DO NOTHING;
