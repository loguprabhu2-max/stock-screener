"""Database connection helper with connection pooling.

Supports TWO connection modes:
  1. DATABASE_URL=postgresql://user:pass@host:port/db   (Render + Supabase use this)
  2. Individual DB_HOST / DB_PORT / DB_NAME / DB_USER / DB_PASSWORD  (local dev)

If DATABASE_URL is set, it takes priority.
"""
import os
from pathlib import Path
import psycopg2
import psycopg2.pool
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

_pool = None


def _build_pool():
    """Create a ThreadedConnectionPool (called once on first use)."""
    db_url = os.getenv("DATABASE_URL")
    if db_url:
        # Cloud connection (Render + Supabase) — single URL string
        if "sslmode=" not in db_url:
            sep = "&" if "?" in db_url else "?"
            db_url = f"{db_url}{sep}sslmode=require"
        return psycopg2.pool.ThreadedConnectionPool(2, 10, dsn=db_url)

    # Local connection — individual env vars
    return psycopg2.pool.ThreadedConnectionPool(
        2, 10,
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_NAME", "stock_screener"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD"),
    )


def _get_pool():
    global _pool
    if _pool is None:
        _pool = _build_pool()
    return _pool


class _PooledConn:
    """Wraps a raw psycopg2 connection so conn.close() returns it to the pool
    instead of destroying it. All other attributes are transparently delegated."""

    def __init__(self, raw, pool):
        self._raw = raw
        self._pool = pool

    def __getattr__(self, name):
        return getattr(self._raw, name)

    def close(self):
        self._pool.putconn(self._raw)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def get_connection():
    """Return a pooled connection. Caller MUST call conn.close() to return it to pool."""
    p = _get_pool()
    return _PooledConn(p.getconn(), p)


def query_all(sql, params=None):
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params or ())
            return cur.fetchall()
    finally:
        conn.close()


def query_one(sql, params=None):
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params or ())
            return cur.fetchone()
    finally:
        conn.close()


def execute(sql, params=None):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
            conn.commit()
    finally:
        conn.close()
