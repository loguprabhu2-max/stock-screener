"""
First-time database setup.
Reads schema.sql, executes it, then creates the default admin user.
Run by START.bat on first launch only.
"""
import sys
from pathlib import Path
from werkzeug.security import generate_password_hash

from database import get_connection, execute, query_one

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = PROJECT_ROOT / "schema.sql"

DEFAULT_USERNAME = "admin"
DEFAULT_PASSWORD = "admin123"


def run_schema():
    print(">>> Running schema.sql ...")
    if not SCHEMA_PATH.exists():
        print(f"ERROR: {SCHEMA_PATH} not found.")
        sys.exit(1)
    sql = SCHEMA_PATH.read_text(encoding="utf-8")
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            conn.commit()
        print(">>> Schema applied successfully.")
    finally:
        conn.close()


def create_default_admin():
    print(">>> Creating default admin user ...")
    existing = query_one(
        "SELECT user_id FROM users WHERE username = %s",
        (DEFAULT_USERNAME,),
    )
    if existing:
        print(f">>> User '{DEFAULT_USERNAME}' already exists. Skipping.")
        return
    pw_hash = generate_password_hash(DEFAULT_PASSWORD)
    execute(
        "INSERT INTO users (username, password_hash, role) VALUES (%s, %s, %s)",
        (DEFAULT_USERNAME, pw_hash, "admin"),
    )
    print("=" * 60)
    print(f"  Admin user created.")
    print(f"  Username: {DEFAULT_USERNAME}")
    print(f"  Password: {DEFAULT_PASSWORD}")
    print("  Please change after first login (later milestone).")
    print("=" * 60)


if __name__ == "__main__":
    try:
        run_schema()
        create_default_admin()
        print(">>> Setup complete.")
    except Exception as e:
        print(f"\nERROR during setup: {e}")
        print("\nMost common causes:")
        print("  - Wrong DB_PASSWORD in .env file")
        print("  - PostgreSQL not running")
        print("  - Database 'stock_screener' not created in pgAdmin")
        sys.exit(1)
