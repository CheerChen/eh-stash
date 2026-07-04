-- 007_gallery_comments.sql
-- Store the actual comment content from exhentai gallery detail pages.
-- Previously only comment_count was kept; the comment bodies (uploader
-- notes, user reviews, source links) were discarded.
--
-- Comments are refreshed alongside the gallery detail: each detail fetch
-- replaces this table's rows for that gid (delete + insert) so stale
-- comments don't accumulate. fetched_at records when this snapshot was
-- taken, matching eh_galleries.last_synced_at.

CREATE TABLE IF NOT EXISTS gallery_comments (
    id                      BIGSERIAL PRIMARY KEY,
    gid                     BIGINT NOT NULL REFERENCES eh_galleries(gid) ON DELETE CASCADE,
    comment_index           INT NOT NULL,          -- 0-based position on the page
    author                  TEXT NOT NULL DEFAULT '',
    author_url              TEXT,
    posted_at               TEXT,                  -- raw "26 June 2026, 15:56" string
    score                   INT,                   -- vote tally, may be NULL when hidden
    body                    TEXT NOT NULL DEFAULT '',
    is_uploader_comment     BOOLEAN NOT NULL DEFAULT FALSE,
    fetched_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (gid, comment_index)
);

CREATE INDEX IF NOT EXISTS idx_gallery_comments_gid
    ON gallery_comments (gid);

CREATE INDEX IF NOT EXISTS idx_gallery_comments_uploader
    ON gallery_comments (gid)
    WHERE is_uploader_comment = TRUE;
