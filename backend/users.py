"""User management - create, list, delete users."""
from werkzeug.security import generate_password_hash
from database import query_all, query_one, execute, get_connection


def list_users():
    return query_all(
        "SELECT user_id, username, role, created_at FROM users ORDER BY username"
    )


def create_user(username, password, role):
    """Returns (success_bool, message)."""
    username = (username or "").strip()
    password = password or ""
    role = (role or "").strip()

    if not username:
        return False, "Username is required."
    if len(username) < 3:
        return False, "Username must be at least 3 characters."
    if len(username) > 50:
        return False, "Username is too long (max 50 chars)."
    if not password:
        return False, "Password is required."
    if len(password) < 6:
        return False, "Password must be at least 6 characters."
    if role not in ("admin", "normal"):
        return False, "Role must be 'admin' or 'normal'."

    existing = query_one(
        "SELECT user_id FROM users WHERE username = %s", (username,)
    )
    if existing:
        return False, f"Username '{username}' already exists."

    pw_hash = generate_password_hash(password)
    try:
        execute(
            "INSERT INTO users (username, password_hash, role) VALUES (%s, %s, %s)",
            (username, pw_hash, role),
        )
        return True, f"User '{username}' created with role '{role}'."
    except Exception as e:
        return False, f"Database error: {e}"


def delete_user(user_id, current_user_id):
    """Cannot delete self. Cannot delete the last admin."""
    user_id = int(user_id)

    if user_id == int(current_user_id):
        return False, "You cannot delete your own account."

    row = query_one(
        "SELECT username, role FROM users WHERE user_id = %s", (user_id,)
    )
    if not row:
        return False, "User not found."

    if row["role"] == "admin":
        admin_count = query_one("SELECT COUNT(*) AS c FROM users WHERE role = 'admin'")
        if admin_count and admin_count["c"] <= 1:
            return False, "Cannot delete the last admin account."

    try:
        execute("DELETE FROM users WHERE user_id = %s", (user_id,))
        return True, f"User '{row['username']}' deleted."
    except Exception as e:
        return False, f"Database error: {e}"


def reset_password(user_id, new_password):
    user_id = int(user_id)
    if not new_password or len(new_password) < 6:
        return False, "Password must be at least 6 characters."

    row = query_one("SELECT username FROM users WHERE user_id = %s", (user_id,))
    if not row:
        return False, "User not found."

    pw_hash = generate_password_hash(new_password)
    try:
        execute(
            "UPDATE users SET password_hash = %s WHERE user_id = %s",
            (pw_hash, user_id),
        )
        return True, f"Password reset for '{row['username']}'."
    except Exception as e:
        return False, f"Database error: {e}"
