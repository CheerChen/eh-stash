-- 005_gallery_groups.sql
-- Gallery version grouping: groups galleries that share the same base Japanese title.

CREATE TABLE IF NOT EXISTS gallery_group_members (
    group_id    BIGINT NOT NULL,            -- oldest gid in the group
    gid         BIGINT NOT NULL REFERENCES eh_galleries(gid),
    UNIQUE(gid)
);

CREATE INDEX IF NOT EXISTS idx_ggm_group_id ON gallery_group_members(group_id);
