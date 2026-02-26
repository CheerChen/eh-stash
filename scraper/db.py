import psycopg2
from psycopg2 import pool
from psycopg2.extras import execute_values
from contextlib import contextmanager
import config

# Create a connection pool
try:
    connection_pool = psycopg2.pool.SimpleConnectionPool(
        1,  # minconn
        10, # maxconn
        config.DATABASE_URL
    )
except Exception as e:
    print(f"Error connecting to database: {e}")
    raise e

@contextmanager
def get_cursor():
    conn = connection_pool.getconn()
    try:
        cur = conn.cursor()
        yield cur, conn
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cur.close()
        connection_pool.putconn(conn)


def get_all_thumb_urls() -> dict[int, str]:
    """返回 {gid: thumb_url}，仅包含 thumb 不为空的记录。"""
    with get_cursor() as (cur, conn):
        cur.execute("SELECT gid, thumb FROM eh_galleries WHERE thumb IS NOT NULL AND thumb != ''")
        return {row[0]: row[1] for row in cur.fetchall()}


def upsert_galleries_bulk(rows: list[tuple]) -> int:
    """Bulk upsert galleries in a single transaction."""
    if not rows:
        return 0

    sql = """
        INSERT INTO eh_galleries (
            gid, token, category, title, title_jpn, uploader, posted_at, language,
            pages, rating, fav_count, comment_count, thumb, tags, last_synced_at, is_active
        ) VALUES %s
        ON CONFLICT (gid) DO UPDATE SET
            token = EXCLUDED.token,
            category = EXCLUDED.category,
            title = EXCLUDED.title,
            title_jpn = EXCLUDED.title_jpn,
            uploader = EXCLUDED.uploader,
            posted_at = EXCLUDED.posted_at,
            language = EXCLUDED.language,
            pages = EXCLUDED.pages,
            rating = EXCLUDED.rating,
            fav_count = EXCLUDED.fav_count,
            comment_count = EXCLUDED.comment_count,
            thumb = EXCLUDED.thumb,
            tags = EXCLUDED.tags,
            last_synced_at = NOW(),
            is_active = TRUE
    """

    template = """
        (%s, %s, %s, %s, %s, %s, %s, %s,
         %s, %s, %s, %s, %s, %s, NOW(), TRUE)
    """

    with get_cursor() as (cur, conn):
        execute_values(cur, sql, rows, template=template, page_size=len(rows))
    return len(rows)
