"""
auth.py
-------
Authentication and Role-Based Access Control (RBAC) Module.
Manages password verification, session tokens, and role-based permissions.
"""

import time
import secrets
from database import get_connection, verify_password

# In-memory session token store (Token -> { user_id, username, role, full_name, expires_at })
SESSIONS = {}

# Role Hierarchy and Module Permissions Matrix
ROLE_PERMISSIONS = {
    "Admin": ["dashboard", "guests", "rooms", "bookings", "checkin", "checkout", "billing", "services", "housekeeping", "reports", "users"],
    "Manager": ["dashboard", "guests", "rooms", "bookings", "checkin", "checkout", "billing", "services", "housekeeping", "reports"],
    "Receptionist": ["dashboard", "guests", "bookings", "checkin", "checkout", "billing", "services"],
    "Housekeeping": ["dashboard", "housekeeping", "rooms"]
}


def authenticate_user(username, password):
    """Authenticates username & password against database."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, username, password_hash, full_name, role FROM users WHERE username = ?", (username,))
    user = cursor.fetchone()
    conn.close()

    if not user:
        return False, "Invalid username or password.", None

    if not verify_password(user["password_hash"], password):
        return False, "Invalid username or password.", None

    # Generate session token valid for 24 hours
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
    
    SESSIONS[token] = session_data

    return True, "Login successful.", session_data


def get_current_user(token):
    """Validates session token and returns user dictionary or None."""
    if not token or token not in SESSIONS:
        return None

    session_data = SESSIONS[token]
    if time.time() > session_data["expires_at"]:
        del SESSIONS[token]
        return None

    return session_data


def check_permission(role, module):
    """Checks if a given role is authorized to access a module."""
    if not role or role not in ROLE_PERMISSIONS:
        return False
    return module in ROLE_PERMISSIONS[role]


def logout_user(token):
    """Destroys an active session token."""
    if token in SESSIONS:
        del SESSIONS[token]
        return True
    return False
