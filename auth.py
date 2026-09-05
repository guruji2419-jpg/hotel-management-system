"""
auth.py
-------
Authentication and Role-Based Access Control (RBAC) Module.
Manages password verification, persistent database-backed session tokens,
and role-based permission matrices across distributed serverless instances.
"""

import time
import secrets
from database import get_connection, verify_password

# In-memory fast cache (synchronized with database)
LOCAL_SESSION_CACHE = {}

# Role Hierarchy and Module Permissions Matrix
ROLE_PERMISSIONS = {
    "Admin": ["dashboard", "guests", "rooms", "bookings", "checkin", "checkout", "billing", "services", "housekeeping", "reports", "users"],
    "Manager": ["dashboard", "guests", "rooms", "bookings", "checkin", "checkout", "billing", "services", "housekeeping", "reports"],
    "Receptionist": ["dashboard", "guests", "bookings", "checkin", "checkout", "billing", "services"],
    "Housekeeping": ["dashboard", "housekeeping", "rooms"]
}


def authenticate_user(username, password):
    """Authenticates username & password against database and persists session token."""
    username = str(username).strip()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, username, password_hash, full_name, role FROM users WHERE username = ?", (username,))
    user = cursor.fetchone()

    if not user:
        conn.close()
        return False, "Invalid username or password.", None

    if not verify_password(user["password_hash"], password):
        conn.close()
        return False, "Invalid username or password.", None

    # Generate cryptographically secure session token valid for 24 hours
    token = secrets.token_hex(24)
    expires_at = time.time() + (24 * 3600)
    
    session_data = {
        "user_id": user["id"],
        "username": user["username"],
        "full_name": user["full_name"],
        "role": user["role"],
        "token": token,
        "expires_at": expires_at
    }
    
    try:
        cursor.execute("""
        INSERT INTO user_sessions (token, user_id, username, full_name, role, expires_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """, (token, user["id"], user["username"], user["full_name"], user["role"], expires_at))
        conn.commit()
    except Exception as e:
        print(f"⚠️ [AUTH] Session store notice: {e}")
    finally:
        conn.close()

    # Update local in-memory cache
    LOCAL_SESSION_CACHE[token] = session_data

    return True, "Login successful.", session_data


def get_current_user(token):
    """Validates session token from persistent database (supporting multi-instance Vercel lambdas)."""
    if not token or not isinstance(token, str):
        return None

    token = token.strip()
    now = time.time()

    # Check local in-memory cache first for high performance
    if token in LOCAL_SESSION_CACHE:
        session = LOCAL_SESSION_CACHE[token]
        if now < session["expires_at"]:
            return session
        else:
            del LOCAL_SESSION_CACHE[token]

    # Validate against persistent database
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT token, user_id, username, full_name, role, expires_at FROM user_sessions WHERE token = ?", (token,))
        row = cursor.fetchone()

        if not row:
            conn.close()
            return None

        expires_at = float(row["expires_at"])
        if now > expires_at:
            cursor.execute("DELETE FROM user_sessions WHERE token = ?", (token,))
            conn.commit()
            conn.close()
            return None

        session_data = {
            "user_id": row["user_id"],
            "username": row["username"],
            "full_name": row["full_name"],
            "role": row["role"],
            "token": row["token"],
            "expires_at": expires_at
        }
        conn.close()

        # Cache locally
        LOCAL_SESSION_CACHE[token] = session_data
        return session_data
    except Exception as e:
        print(f"⚠️ [AUTH] Session validation error: {e}")
        return None


def check_permission(role, module):
    """Checks if a given role is authorized to access a module."""
    if not role or role not in ROLE_PERMISSIONS:
        return False
    return module in ROLE_PERMISSIONS[role]


def logout_user(token):
    """Destroys an active session token in database and local cache."""
    if not token:
        return False

    token = token.strip()
    if token in LOCAL_SESSION_CACHE:
        del LOCAL_SESSION_CACHE[token]

    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM user_sessions WHERE token = ?", (token,))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"⚠️ [AUTH] Logout error: {e}")
        return False
