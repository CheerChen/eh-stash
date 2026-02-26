import os
import psycopg2
from psycopg2 import pool
from contextlib import contextmanager
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

try:
    connection_pool = psycopg2.pool.SimpleConnectionPool(
        1, 10, DATABASE_URL
    )
except Exception as e:
    print(f"Error connecting to database: {e}")
    raise e

@contextmanager
def get_cursor():
    conn = connection_pool.getconn()
    try:
        cur = conn.cursor()
        yield cur
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cur.close()
        connection_pool.putconn(conn)

def get_db():
    with get_cursor() as cur:
        yield cur
