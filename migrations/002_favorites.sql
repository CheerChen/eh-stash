-- 002_favorites.sql
-- User signal: which galleries the user has favorited. This is behavior data,
-- kept separate from the gallery source data in eh_galleries. The cosine
-- recommendation system (003_recommendation.sql) consumes this to build the
-- user profile vector.

CREATE TABLE IF NOT EXISTS user_favorites (
    gid          BIGINT PRIMARY KEY REFERENCES eh_galleries(gid),
    favorited_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
