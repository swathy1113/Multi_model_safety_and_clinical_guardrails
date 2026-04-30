"""
auth.py — Authentication using only Python built-ins
No external packages needed — uses hashlib + secrets

ROLES:
  admin  — full access, manages users and patients
  doctor — can view patients, update care plans, set medication times
  carer  — can use all scanning tools, view patients, reminders
"""

import hashlib
import secrets
import os
from database import get_conn


def hash_password(password: str) -> str:
    """SHA-256 hash with a random salt — stored as salt:hash"""
    salt = secrets.token_hex(16)
    hashed = hashlib.sha256(f"{salt}{password}".encode()).hexdigest()
    return f"{salt}:{hashed}"


def verify_password(password: str, stored: str) -> bool:
    """Verify password against stored salt:hash"""
    try:
        salt, hashed = stored.split(":", 1)
        check = hashlib.sha256(f"{salt}{password}".encode()).hexdigest()
        return check == hashed
    except Exception:
        return False


def generate_token() -> str:
    return secrets.token_hex(32)


# ─── DB setup ─────────────────────────────────────────────────────

def create_users_table():
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id         SERIAL PRIMARY KEY,
                username   VARCHAR(100) UNIQUE NOT NULL,
                password   VARCHAR(200) NOT NULL,
                full_name  VARCHAR(150) NOT NULL,
                role       VARCHAR(20)  NOT NULL DEFAULT 'carer',
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                token      VARCHAR(100) PRIMARY KEY,
                user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                username   VARCHAR(100) NOT NULL,
                full_name  VARCHAR(150) NOT NULL,
                role       VARCHAR(20)  NOT NULL,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        conn.commit()
        cur.close()
        print("[Auth] users + sessions tables ready.")
    except Exception as e:
        conn.rollback()
        print(f"[Auth] create_users_table error: {e}")
    finally:
        conn.close()


# ─── Auth operations ──────────────────────────────────────────────

def register_user(username: str, password: str, full_name: str, role: str = "carer") -> dict:
    """Register a new user. Returns error if username taken."""
    if role not in ("admin", "doctor", "carer"):
        return {"error": "Role must be admin, doctor, or carer"}
    if len(password) < 6:
        return {"error": "Password must be at least 6 characters"}

    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id FROM users WHERE username=%s", (username,))
        if cur.fetchone():
            return {"error": "Username already taken"}
        pw_hash = hash_password(password)
        cur.execute(
            "INSERT INTO users (username, password, full_name, role) VALUES (%s,%s,%s,%s) RETURNING id",
            (username.strip().lower(), pw_hash, full_name.strip(), role)
        )
        user_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        print(f"[Auth] Registered: {username} as {role}")
        return {"success": True, "user_id": user_id, "username": username, "role": role}
    except Exception as e:
        conn.rollback()
        print(f"[Auth] register error: {e}")
        return {"error": str(e)}
    finally:
        conn.close()


def login_user(username: str, password: str) -> dict:
    """Verify credentials, create session token, return it."""
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, password, full_name, role FROM users WHERE username=%s",
            (username.strip().lower(),)
        )
        row = cur.fetchone()
        if not row:
            return {"error": "Username not found"}
        user_id, stored_pw, full_name, role = row
        if not verify_password(password, stored_pw):
            return {"error": "Incorrect password"}

        # Create session token
        token = generate_token()
        cur.execute(
            "INSERT INTO sessions (token, user_id, username, full_name, role) VALUES (%s,%s,%s,%s,%s)",
            (token, user_id, username.strip().lower(), full_name, role)
        )
        conn.commit()
        cur.close()
        print(f"[Auth] Login: {username} ({role})")
        return {
            "success":   True,
            "token":     token,
            "username":  username.strip().lower(),
            "full_name": full_name,
            "role":      role
        }
    except Exception as e:
        conn.rollback()
        print(f"[Auth] login error: {e}")
        return {"error": str(e)}
    finally:
        conn.close()


def get_session(token: str) -> dict:
    """Validate token and return user info, or None if invalid."""
    if not token:
        return None
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT username, full_name, role FROM sessions WHERE token=%s",
            (token,)
        )
        row = cur.fetchone()
        cur.close()
        if not row:
            return None
        return {"username": row[0], "full_name": row[1], "role": row[2]}
    except Exception as e:
        print(f"[Auth] get_session error: {e}")
        return None
    finally:
        conn.close()


def logout_user(token: str) -> bool:
    """Delete session token."""
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM sessions WHERE token=%s", (token,))
        conn.commit()
        cur.close()
        return True
    except Exception as e:
        conn.rollback()
        return False
    finally:
        conn.close()


def get_all_users() -> list:
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, username, full_name, role, created_at FROM users ORDER BY created_at DESC")
        rows = cur.fetchall()
        cur.close()
        return [{"id": r[0], "username": r[1], "full_name": r[2], "role": r[3],
                 "created_at": r[4].strftime("%d %b %Y") if r[4] else ""} for r in rows]
    except Exception as e:
        print(f"[Auth] get_all_users error: {e}")
        return []
    finally:
        conn.close()