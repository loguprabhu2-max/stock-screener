"""Database connection helper.

Supports TWO connection modes:
  1. DATABASE_URL=postgresql://user:pass@host:port/db   (Render + Supabase use this)
  2. Individual DB_HOST / DB_PORT / DB_NAME / DB_USER / DB_PASSWORD  (local dev)

If DATABASE_URL is set, it takes priority.
"""
import os
from pathlib import Path
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


def get_connection():
    db_url = os.getenv("DATABASE_URL")
    if db_url:
        # Cloud connection (Render + Supabase) — single URL string
        # Supabase requires SSL; sslmode=require is added if not already in URL
        if "sslmode=" not in db_url:
            sep = "&" if "?" in db_url else "?"
            db_url = f"{db_url}{sep}sslmode=require"
        return psycopg2.connect(db_url)

    # Local connection — individual env vars
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_NAME", "stock_screener"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD"),
    )


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
