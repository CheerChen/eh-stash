-- 006_detail_extras.sql
-- Capture fields present on the exhentai detail page but previously discarded
-- by ParseDetail. All new columns are nullable so existing rows (old-style
-- detail) keep NULL — that NULL is the signal that a row still needs a
-- refresh-detail pass to backfill the new fields.
--
-- New columns:
--   file_size        raw size string from #gdd ("3.54 GiB")
--   file_size_bytes  parsed numeric bytes, for sorting / filtering
--   rating_count     number of raters (#rating_count)
--   visible          visibility flag from #gdd ("Yes" | "No (Replaced)" | ...)
--   parent_gid       gid extracted from the Parent: link, when present
--   torrent_count    "Torrent Download (N)" count
--   is_expunged      TRUE when visible contains "Replaced" or an expunged
--                    banner is detected. Distinct from is_active (soft-delete
--                    from list scanning) — is_expunged reflects EH's own
--                    replacement state.

ALTER TABLE eh_galleries
    ADD COLUMN IF NOT EXISTS file_size       TEXT,
    ADD COLUMN IF NOT EXISTS file_size_bytes BIGINT,
    ADD COLUMN IF NOT EXISTS rating_count    INT,
    ADD COLUMN IF NOT EXISTS visible         TEXT,
    ADD COLUMN IF NOT EXISTS parent_gid      BIGINT,
    ADD COLUMN IF NOT EXISTS torrent_count   INT DEFAULT 0,
    ADD COLUMN IF NOT EXISTS is_expunged     BOOLEAN NOT NULL DEFAULT FALSE;

-- Refresh candidates: old-style detail rows (file_size IS NULL).
-- Partial index keeps this cheap as the backfill progresses.
CREATE INDEX IF NOT EXISTS idx_eh_galleries_refresh_pending
    ON eh_galleries (gid)
    WHERE file_size IS NULL AND is_active = TRUE;

-- Parent link lookups for frontend de-duplication.
CREATE INDEX IF NOT EXISTS idx_eh_galleries_parent_gid
    ON eh_galleries (parent_gid)
    WHERE parent_gid IS NOT NULL;

-- Expunged filter for recommendation / listing queries.
CREATE INDEX IF NOT EXISTS idx_eh_galleries_not_expunged
    ON eh_galleries (gid)
    WHERE is_expunged = FALSE;
