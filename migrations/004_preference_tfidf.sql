-- 004_preference_tfidf.sql
-- Add raw count column to preference_tags; weight now stores TF-IDF instead of raw count.

ALTER TABLE preference_tags ADD COLUMN IF NOT EXISTS count REAL NOT NULL DEFAULT 0;
COMMENT ON COLUMN preference_tags.weight IS 'TF-IDF score: count * ln(N / df)';
COMMENT ON COLUMN preference_tags.count  IS 'Raw occurrence count in user favorites';
