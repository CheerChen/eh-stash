-- 003_recommendation.sql
-- Cosine vector recommendation via pgvector sparse embeddings.
--
-- Requires the postgres image to bundle the vector extension
-- (e.g. pgvector/pgvector:pg16).
--
-- Pipeline:
--   1. tag_vocabulary maps each qualifying (namespace, tag) to a stable dim.
--   2. The embedding worker fills recommended_cache.tag_embedding from each
--      gallery's tags using that vocabulary.
--   3. The user_profile vector is rebuilt from user_favorites via the same
--      vocabulary.
--   4. recommended_cache.similarity = cosine(profile, gallery_embedding).

CREATE EXTENSION IF NOT EXISTS vector;

-- Tag vocabulary: stable (namespace, tag) -> dim mapping. dim is allocated
-- monotonically and never reused. Tags falling below a count threshold get
-- is_active = FALSE but keep their dim ("dead dim") to avoid recomputing
-- every gallery embedding; sparse storage makes this effectively free.
CREATE TABLE IF NOT EXISTS tag_vocabulary (
    dim         INTEGER PRIMARY KEY,
    namespace   TEXT NOT NULL,
    tag         TEXT NOT NULL,
    idf         DOUBLE PRECISION NOT NULL,
    type_weight DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(namespace, tag)
);

CREATE INDEX IF NOT EXISTS idx_tag_vocabulary_active
    ON tag_vocabulary(dim)
    WHERE is_active = TRUE;

-- Vocabulary metadata: next-free dim + gallery-count snapshot used as the
-- IDF base. Single row, id = 1.
CREATE TABLE IF NOT EXISTS tag_vocabulary_meta (
    id              INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    dim_count       INTEGER NOT NULL DEFAULT 0,
    active_count    INTEGER NOT NULL DEFAULT 0,
    total_galleries BIGINT  NOT NULL DEFAULT 0,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO tag_vocabulary_meta (id) VALUES (1)
    ON CONFLICT (id) DO NOTHING;

-- User profile vector. Single user, recomputed from scratch on favorites
-- changes to avoid floating-point drift.
CREATE TABLE IF NOT EXISTS user_profile (
    id          INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    embedding   sparsevec(65536),
    liked_count INTEGER NOT NULL DEFAULT 0,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO user_profile (id, liked_count) VALUES (1, 0)
    ON CONFLICT (id) DO NOTHING;

-- App settings: tunable knobs that survive restarts. The recommendation
-- workers read similarity_threshold here.
CREATE TABLE IF NOT EXISTS app_settings (
    key   TEXT PRIMARY KEY,
    value JSONB NOT NULL
);

INSERT INTO app_settings (key, value) VALUES
    ('similarity_threshold', '0.3'::jsonb)
ON CONFLICT (key) DO NOTHING;

-- Per-gallery derived recommendation state.
-- Dim 65536 is a generous upper bound; sparsevec only stores non-zero entries
-- so the cap has effectively zero storage cost.
CREATE TABLE IF NOT EXISTS recommended_cache (
    gid           BIGINT PRIMARY KEY REFERENCES eh_galleries(gid),
    similarity    REAL,
    tag_embedding sparsevec(65536),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_recommended_cache_embedding_pending
    ON recommended_cache (gid)
    WHERE tag_embedding IS NULL;

CREATE INDEX IF NOT EXISTS idx_recommended_cache_similarity
    ON recommended_cache (similarity DESC)
    WHERE similarity IS NOT NULL;
