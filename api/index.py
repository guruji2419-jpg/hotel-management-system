"""
api/index.py
------------
Enterprise REST API Engine for Grand Horizon Hotel Management System.
Features:
- Dual-Engine Support: PostgreSQL (Production / Vercel) & SQLite (Local)
- Persistent Database-Backed RBAC Authentication & Session Validation
- Robust Overlap Prevention with HTTP 409 Conflict Status
- Synchronized Room & Housekeeping State Machine
- Itemized Invoicing, Addon Services & Billing Records
- Standardized RESTful Response Structures (200, 201, 400, 401, 403, 404, 409, 500)
- Vercel Serverless Function & Standalone Local Execution Compatibility
"""

import os
import sys
import csv
import io
import traceback
from datetime import datetime

# Ensure root directory is in Python path
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from flask import Flask, jsonify, request, send_from_directory, Response
from flask_cors import CORS

from database import get_connection, hash_password, init_db, get_database_type
from auth import authenticate_user, get_current_user, check_permission, logout_user, normalize_role
from hotel_manager import (
    load_rooms, api_check_in, api_check_out, api_get_stats,
    log_room_maintenance, resolve_room_maintenance, get_maintenance_logs
)

# Ensure database tables are initialized
try:
    init_db()
except Exception as _e:
    print(f"⚠️ [API] DB init notice: {_e}")

app = Flask(__name__, static_folder=parent_dir, static_url_path="")
# CORS configured for application routes
CORS(app, resources={r"/api/*": {"origins": "*"}})


# ==========================================================================
# HELPER FUNCTIONS & RESPONSE STANDARDIZATION
# ==========================================================================

def extract_auth_token():
    """Safely extracts authorization token from headers or query parameters."""
    auth_header = request.headers.get("Authorization", "").strip()
    token = ""
    if auth_header:
        parts = auth_header.split(None, 1)
        if len(parts) == 2 and parts[0].lower() == "bearer":
            token = parts[1].strip()
        elif len(parts) == 1:
            token = parts[0].strip()

    if not token:
        token = request.headers.get("X-Auth-Token", "").strip() or request.headers.get("X-Session-Token", "").strip()

    if not token and "token" in request.args:
        token = request.args.get("token", "").strip()

    return token


def get_auth_user():
    """Extracts and validates user from Bearer header, custom token headers, or query token."""
    token = extract_auth_token()
    return get_current_user(token)


def api_success(data=None, message="Operation successful", status_code=200):
    """Standardized success response wrapper."""
    payload = {
        "success": True,
        "message": message
    }
    if data is not None:
        if isinstance(data, dict):
            payload.update(data)
        else:
            payload["data"] = data
    return jsonify(payload), status_code


def api_error(message="An error occurred", status_code=400, error_detail=None):
    """Standardized error response wrapper."""
    payload = {
        "success": False,
        "error": message,
        "message": message
    }
    if error_detail:
        print(f"❌ [API Error {status_code}]: {message} | Details: {error_detail}")
    return jsonify(payload), status_code


# ==========================================================================
# STATIC FRONT-END ROUTING
# ==========================================================================

@app.route("/")
def serve_index():
    return send_from_directory(parent_dir, "index.html")


@app.route("/<path:path>")
def serve_static(path):
    full_path = os.path.join(parent_dir, path)
    if os.path.exists(full_path) and not os.path.isdir(full_path):
        return send_from_directory(parent_dir, path)
    return send_from_directory(parent_dir, "index.html")


# ==========================================================================
# 1. AUTHENTICATION & RBAC ENDPOINTS
# ==========================================================================

@app.route("/api/auth/login", methods=["POST"])
def login():
    try:
        data = request.get_json() or {}
        username = data.get("username", "").strip()
        password = data.get("password", "").strip()

        if not username or not password:
            return api_error("Username and password are required.", 400)

        success, msg, session_data = authenticate_user(username, password)
        if not success:
            return api_error(msg, 401)

        return api_success({"user": session_data}, message=msg, status_code=200)
    except Exception as e:
        traceback.print_exc()
        return api_error("Authentication failed due to a server error.", 500, error_detail=str(e))


@app.route("/api/auth/me", methods=["GET"])
def get_me():
    try:
        user = get_auth_user()
        if not user:
            return api_error("Session expired or unauthorized.", 401)
        return api_success({"user": user})
    except Exception as e:
        return api_error("Unable to verify session.", 500, error_detail=str(e))


@app.route("/api/auth/logout", methods=["POST"])
def logout():
    try:
        token = extract_auth_token()
        if token:
            logout_user(token)
        return api_success(message="Logged out successfully.")
    except Exception as e:
        return api_error("Logout failed.", 500, error_detail=str(e))


@app.route("/api/auth/users", methods=["GET", "POST"])
def manage_users():
    try:
        user = get_auth_user()
        if not user or normalize_role(user.get("role")) != "Admin":
            return api_error("Admin authorization required.", 403)

        conn = get_connection()
        cursor = conn.cursor()

        if request.method == "POST":
            data = request.get_json() or {}
            username = data.get("username", "").strip()
            password = data.get("password", "").strip()
            full_name = data.get("full_name", "").strip()
            role = data.get("role", "Receptionist")

            if not username or not password or not full_name:
                conn.close()
                return api_error("All fields are required to create staff member.", 400)

            try:
                pwd_hash = hash_password(password)
                cursor.execute(
                    "INSERT INTO users (username, password_hash, full_name, role) VALUES (?, ?, ?, ?)",
                    (username, pwd_hash, full_name, role)
                )
                conn.commit()
                conn.close()
                return api_success(message=f"Staff user '{username}' created successfully.", status_code=201)
            except Exception as e:
                conn.close()
                return api_error(f"Failed to create user: {e}", 400)

        cursor.execute("SELECT id, username, full_name, role, created_at FROM users ORDER BY id ASC")
        users = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return api_success({"users": users})
    except Exception as e:
        return api_error("Unable to process user management request.", 500, error_detail=str(e))


# ==========================================================================
# 2. GUEST MANAGEMENT ENDPOINTS
# ==========================================================================

@app.route("/api/guests", methods=["GET", "POST"])
def handle_guests():
    try:
        user = get_auth_user()
        if not user or not check_permission(user.get("role"), "guests"):
            return api_error("Access denied.", 403)

        conn = get_connection()
        cursor = conn.cursor()

        if request.method == "POST":
            data = request.get_json() or {}
            full_name = data.get("full_name", "").strip()
            phone = data.get("phone", "").strip()

            if not full_name or not phone:
                conn.close()
                return api_error("Guest Full Name and Phone number are required.", 400)

            dob = data.get("dob")
            age = int(data.get("age", 25)) if str(data.get("age", "")).isdigit() else 25
            gender = data.get("gender", "Other")
            email = data.get("email", "").strip()
            address = data.get("address", "").strip()
            city = data.get("city", "").strip()
            state = data.get("state", "").strip()
            country = data.get("country", "India").strip()
            nationality = data.get("nationality", "Indian").strip()
            id_type = data.get("id_proof_type", "Aadhaar / Passport")
            id_num = data.get("id_proof_number", "").strip()
            emergency_name = data.get("emergency_name", "").strip()
            emergency_phone = data.get("emergency_phone", "").strip()
            adults = int(data.get("adults", 1)) if str(data.get("adults", "")).isdigit() else 1
            children = int(data.get("children", 0)) if str(data.get("children", "")).isdigit() else 0
            special_req = data.get("special_requests", "").strip()
            notes = data.get("notes", "").strip()

            cursor.execute("""
            INSERT INTO guests (
                full_name, dob, age, gender, phone, email, address, city, state, country,
                nationality, id_proof_type, id_proof_number, emergency_name, emergency_phone,
                adults, children, special_requests, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                full_name, dob, age, gender, phone, email, address, city, state, country,
                nationality, id_type, id_num, emergency_name, emergency_phone,
                adults, children, special_req, notes
            ))
            conn.commit()
            guest_id = cursor.lastrowid
            conn.close()
            return api_success({"guest_id": guest_id}, message=f"Guest '{full_name}' created successfully.", status_code=201)

        # GET Query with optional search query
        query = request.args.get("q", "").strip()
        if query:
            cursor.execute("""
            SELECT * FROM guests 
            WHERE LOWER(full_name) LIKE LOWER(?) OR phone LIKE ? OR email LIKE ? OR id_proof_number LIKE ?
            ORDER BY id DESC
            """, (f"%{query}%", f"%{query}%", f"%{query}%", f"%{query}%"))
        else:
            cursor.execute("SELECT * FROM guests ORDER BY id DESC LIMIT 100")

        guests = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return api_success({"guests": guests})
    except Exception as e:
        traceback.print_exc()
        return api_error("Unable to load or create guest.", 500, error_detail=str(e))


@app.route("/api/guests/<int:guest_id>", methods=["GET", "PUT", "DELETE"])
def handle_single_guest(guest_id):
    try:
        user = get_auth_user()
        if not user or not check_permission(user.get("role"), "guests"):
            return api_error("Access denied.", 403)

        conn = get_connection()
        cursor = conn.cursor()

        if request.method == "DELETE":
            if normalize_role(user.get("role")) not in ["Admin", "Manager", "Receptionist"]:
                conn.close()
                return api_error("Delete permission denied. Admin, Manager, or Receptionist role required.", 403)
            # Prevent deletion if guest has active bookings
            cursor.execute("SELECT COUNT(*) as cnt FROM bookings WHERE guest_id = ? AND status IN ('Confirmed', 'Checked-in', 'Reserved')", (guest_id,))
            active_b = cursor.fetchone()
            cnt = (active_b["cnt"] if isinstance(active_b, dict) else active_b[0]) if active_b else 0
            if cnt > 0:
                conn.close()
                return api_error("Cannot delete guest with active reservations or check-ins.", 400)
            cursor.execute("DELETE FROM guests WHERE id = ?", (guest_id,))
            conn.commit()
            conn.close()
            return api_success(message="Guest record deleted successfully.")

        if request.method == "PUT":
            data = request.get_json() or {}
            cursor.execute("""
            UPDATE guests SET 
                full_name = COALESCE(?, full_name), 
                phone = COALESCE(?, phone), 
                email = COALESCE(?, email), 
                address = COALESCE(?, address), 
                city = COALESCE(?, city), 
                country = COALESCE(?, country),
                id_proof_type = COALESCE(?, id_proof_type), 
                id_proof_number = COALESCE(?, id_proof_number), 
                emergency_name = COALESCE(?, emergency_name), 
                emergency_phone = COALESCE(?, emergency_phone),
                special_requests = COALESCE(?, special_requests), 
                notes = COALESCE(?, notes), 
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """, (
                data.get("full_name"), data.get("phone"), data.get("email"), data.get("address"),
                data.get("city"), data.get("country"), data.get("id_proof_type"), data.get("id_proof_number"),
                data.get("emergency_name"), data.get("emergency_phone"), data.get("special_requests"),
                data.get("notes"), guest_id
            ))
            conn.commit()
            conn.close()
            return api_success(message="Guest profile updated successfully.")

        # GET single guest with booking & payment history
        cursor.execute("SELECT * FROM guests WHERE id = ?", (guest_id,))
        guest_row = cursor.fetchone()
        if not guest_row:
            conn.close()
            return api_error("Guest not found.", 404)

        guest_dict = dict(guest_row)

        cursor.execute("""
        SELECT b.*, r.room_number, r.room_type 
        FROM bookings b 
        JOIN rooms r ON b.room_id = r.id 
        WHERE b.guest_id = ? 
        ORDER BY b.id DESC
        """, (guest_id,))
        bookings = [dict(row) for row in cursor.fetchall()]

        cursor.execute("""
        SELECT p.*, i.grand_total 
        FROM payments p 
        JOIN invoices i ON p.booking_id = i.booking_id 
        WHERE i.guest_id = ? 
        ORDER BY p.id DESC
        """, (guest_id,))
        payments = [dict(row) for row in cursor.fetchall()]

        conn.close()
        return api_success({"guest": guest_dict, "bookings": bookings, "payments": payments})
    except Exception as e:
        traceback.print_exc()
        return api_error("Unable to process guest record.", 500, error_detail=str(e))


# ==========================================
# 3. ROOM MANAGEMENT ENDPOINTS
# ==========================================

@app.route("/api/rooms", methods=["GET", "POST"])
def handle_rooms():
    try:
        if request.method == "POST":
            user = get_auth_user()
            if not user or normalize_role(user.get("role")) not in ["Admin", "Manager"]:
                return api_error("Access denied. Admin or Manager role required to create rooms.", 403)

            data = request.get_json() or {}
            r_num = data.get("room_number", "").strip()
            r_type = data.get("room_type", "Standard")
            price = float(data.get("price_per_night", 50.0))
            floor = int(data.get("floor", 1))
            bed_type = data.get("bed_type", "Double")
            capacity = int(data.get("capacity", 2))
            ac_type = data.get("ac_type", "AC")
            amenities = data.get("amenities", "WiFi, TV")
            desc = data.get("description", "")

            if not r_num:
                return api_error("Room number is required.", 400)

            conn = get_connection()
            cursor = conn.cursor()
            try:
                cursor.execute("""
                INSERT INTO rooms (room_number, floor, room_type, bed_type, capacity, price_per_night, ac_type, amenities, description)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (r_num, floor, r_type, bed_type, capacity, price, ac_type, amenities, desc))

                cursor.execute("INSERT OR IGNORE INTO housekeeping (room_number, cleaning_status) VALUES (?, 'Clean')", (r_num,))
                conn.commit()
                conn.close()
                return api_success(message=f"Room {r_num} created successfully.", status_code=201)
            except Exception as e:
                conn.close()
                return api_error(f"Room creation error: {e}", 400)

        conn = get_connection()
        cursor = conn.cursor()

        # GET logic with optional filters
        status_filter = request.args.get("status")
        type_filter = request.args.get("type")

        sql = """
        SELECT r.*, g.full_name as guest, b.check_in_date, b.check_out_date, b.id as active_booking_id
        FROM rooms r
        LEFT JOIN bookings b ON r.id = b.room_id AND b.status = 'Checked-in'
        LEFT JOIN guests g ON b.guest_id = g.id
        WHERE 1=1
        """
        params = []
        if status_filter:
            sql += " AND r.status = ?"
            params.append(status_filter)
        if type_filter:
            sql += " AND r.room_type = ?"
            params.append(type_filter)

        sql += " ORDER BY r.room_number ASC"

        cursor.execute(sql, params)
        rows = cursor.fetchall()
        conn.close()

        rooms_list = [dict(row) for row in rows]
        
        # Backward-compatible dictionary
        rooms_dict = {}
        for r in rooms_list:
            rooms_dict[str(r["room_number"])] = {
                "id": r["id"],
                "type": r["room_type"],
                "price": float(r["price_per_night"]),
                "status": r["status"],
                "guest": r["guest"],
                "housekeeping_status": r["housekeeping_status"],
                "floor": r["floor"],
                "capacity": r["capacity"],
                "amenities": r["amenities"],
                "active_booking_id": r["active_booking_id"]
            }

        return api_success({"rooms": rooms_dict, "list": rooms_list})
    except Exception as e:
        traceback.print_exc()
        return api_error("Unable to load rooms.", 500, error_detail=str(e))


@app.route("/api/rooms/<int:room_id>", methods=["PUT", "DELETE"])
def handle_single_room(room_id):
    try:
        user = get_auth_user()
        if not user or not check_permission(user.get("role"), "rooms"):
            return api_error("Access denied.", 403)

        conn = get_connection()
        cursor = conn.cursor()

        if request.method == "DELETE":
            if normalize_role(user.get("role")) not in ["Admin", "Manager"]:
                conn.close()
                return api_error("Delete permission denied. Admin or Manager role required.", 403)

            cursor.execute("SELECT status, room_number FROM rooms WHERE id = ?", (room_id,))
            r_check = cursor.fetchone()
            if not r_check:
                conn.close()
                return api_error("Room not found.", 404)
            if r_check["status"] == "Occupied":
                conn.close()
                return api_error(f"Cannot delete Room {r_check['room_number']} because it is currently Occupied.", 400)

            cursor.execute("SELECT COUNT(*) as cnt FROM bookings WHERE room_id = ? AND status IN ('Confirmed', 'Checked-in')", (room_id,))
            b_active = cursor.fetchone()
            cnt = (b_active["cnt"] if isinstance(b_active, dict) else b_active[0]) if b_active else 0
            if cnt > 0:
                conn.close()
                return api_error(f"Cannot delete Room {r_check['room_number']}: Active or upcoming reservations exist.", 400)

            # Clean up associated housekeeping record
            cursor.execute("DELETE FROM housekeeping WHERE room_number = ?", (r_check["room_number"],))
            cursor.execute("DELETE FROM rooms WHERE id = ?", (room_id,))
            conn.commit()
            conn.close()
            return api_success(message="Room deleted successfully.")

        if request.method == "PUT":
            data = request.get_json() or {}
            new_room_number = data.get("room_number")
            new_status = data.get("status")
            new_hk_status = data.get("housekeeping_status")

            # Check if updating room_number causes duplicate
            if new_room_number:
                cursor.execute("SELECT id FROM rooms WHERE room_number = ? AND id != ?", (new_room_number, room_id))
                if cursor.fetchone():
                    conn.close()
                    return api_error(f"Room number {new_room_number} already exists.", 409)

            # Get current room number before update
            cursor.execute("SELECT room_number FROM rooms WHERE id = ?", (room_id,))
            curr_row = cursor.fetchone()
            old_room_number = curr_row["room_number"] if curr_row else None

            cursor.execute("""
            UPDATE rooms SET 
                room_number = COALESCE(?, room_number),
                floor = COALESCE(?, floor),
                room_type = COALESCE(?, room_type),
                bed_type = COALESCE(?, bed_type),
                price_per_night = COALESCE(?, price_per_night),
                status = COALESCE(?, status),
                housekeeping_status = COALESCE(?, housekeeping_status),
                amenities = COALESCE(?, amenities),
                capacity = COALESCE(?, capacity)
            WHERE id = ?
            """, (
                new_room_number,
                data.get("floor"),
                data.get("room_type"),
                data.get("bed_type"),
                data.get("price_per_night"),
                new_status,
                new_hk_status,
                data.get("amenities"),
                data.get("capacity"),
                room_id
            ))

            # If room_number changed, update housekeeping table
            if new_room_number and old_room_number and new_room_number != old_room_number:
                cursor.execute("UPDATE housekeeping SET room_number = ? WHERE room_number = ?", (new_room_number, old_room_number))

            # Sync with housekeeping table if status changed
            if new_hk_status or new_status:
                target_room_num = new_room_number or old_room_number
                if target_room_num:
                    hk_val = new_hk_status or ("Clean" if new_status == "Available" else "Cleaning")
                    cursor.execute("""
                    UPDATE housekeeping SET cleaning_status = ?, last_updated = CURRENT_TIMESTAMP
                    WHERE room_number = ?
                    """, (hk_val, target_room_num))

            conn.commit()
            conn.close()
            return api_success(message="Room updated successfully.")
    except Exception as e:
        traceback.print_exc()
        return api_error("Unable to update room.", 500, error_detail=str(e))


# ==========================================================================
# 4. RESERVATIONS & OVERLAP PREVENTION
# ==========================================================================

@app.route("/api/bookings", methods=["GET", "POST"])
def handle_bookings():
    try:
        user = get_auth_user()
        if not user or not check_permission(user.get("role"), "bookings"):
            return api_error("Access denied.", 403)

        conn = get_connection()
        cursor = conn.cursor()

        if request.method == "POST":
            data = request.get_json() or {}
            guest_id = data.get("guest_id")
            room_id = data.get("room_id")
            check_in_date = data.get("check_in_date")
            check_out_date = data.get("check_out_date")
            adults = int(data.get("adults", 1))
            children = int(data.get("children", 0))
            advance = float(data.get("advance_payment", 0.0))
            discount = float(data.get("discount", 0.0))
            source = data.get("booking_source", "Direct Website")

            if not guest_id or not room_id or not check_in_date or not check_out_date:
                conn.close()
                return api_error("Guest, Room, Check-in and Check-out dates are required.", 400)

            try:
                guest_id = int(guest_id)
                room_id = int(room_id)
            except (ValueError, TypeError):
                conn.close()
                return api_error("Invalid guest_id or room_id.", 400)

            # Date calculation
            try:
                from datetime import datetime
                cin = datetime.strptime(check_in_date, "%Y-%m-%d")
                cout = datetime.strptime(check_out_date, "%Y-%m-%d")
                nights = (cout - cin).days
                if nights < 1:
                    conn.close()
                    return api_error("Check-out date must be after check-in date.", 400)
            except Exception:
                conn.close()
                return api_error("Invalid date format. Use YYYY-MM-DD.", 400)

            # Check room exists and get price
            cursor.execute("SELECT price_per_night, status FROM rooms WHERE id = ?", (room_id,))
            rm = cursor.fetchone()
            if not rm:
                conn.close()
                return api_error("Room not found.", 404)
            if rm["status"] == "Maintenance":
                conn.close()
                return api_error("Room is under maintenance and cannot be booked.", 409)

            # CRITICAL SERVER-SIDE OVERLAP PREVENTION
            overlap_query = """
            SELECT id, booking_code, check_in_date, check_out_date, status FROM bookings
            WHERE room_id = ? 
              AND status IN ('Confirmed', 'Checked-in')
              AND NOT (check_out_date <= ? OR check_in_date >= ?)
            """
            cursor.execute(overlap_query, (room_id, check_in_date, check_out_date))
            conflict = cursor.fetchone()
            if conflict:
                conn.close()
                return api_error(
                    f"OVERLAP DETECTED! Room is already reserved/occupied from {conflict['check_in_date']} to {conflict['check_out_date']}.",
                    409
                )

            # Deterministic Math
            room_price = float(rm["price_per_night"])
            subtotal = room_price * nights
            tax_rate = 12.0
            tax_amount = subtotal * (tax_rate / 100.0)
            grand_total = subtotal + tax_amount - discount

            booking_code = f"RES-{int(os.urandom(3).hex(), 16)}"
            cursor.execute("""
            INSERT INTO bookings (
                booking_code, guest_id, room_id, check_in_date, check_out_date, adults, children, 
                booking_source, advance_payment, room_price, tax_amount, discount, grand_total, status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Confirmed')
            """, (
                booking_code, guest_id, room_id, check_in_date, check_out_date, adults, children, 
                source, advance, room_price, tax_amount, discount, grand_total
            ))
            
            new_booking_id = cursor.lastrowid
            # Only update status if it was 'Available', but keep its current state if it's 'Cleaning' or 'Occupied'
            cursor.execute("UPDATE rooms SET status = 'Reserved' WHERE id = ? AND status = 'Available'", (room_id,))

            conn.commit()
            conn.close()
            return api_success({"booking_code": booking_code, "booking_id": new_booking_id}, message=f"Reservation {booking_code} confirmed successfully!", status_code=201)

        # GET Bookings List
        cursor.execute("""
        SELECT b.*, g.full_name as guest_name, g.phone as guest_phone, r.room_number, r.room_type, r.price_per_night
        FROM bookings b
        JOIN guests g ON b.guest_id = g.id
        JOIN rooms r ON b.room_id = r.id
        ORDER BY b.id DESC
        """)
        bookings = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return api_success({"bookings": bookings})
    except Exception as e:
        traceback.print_exc()
        return api_error("Unable to load or create reservations.", 500, error_detail=str(e))


@app.route("/api/bookings/<int:booking_id>", methods=["PUT", "DELETE"])
def handle_single_booking(booking_id):
    try:
        user = get_auth_user()
        if not user or not check_permission(user.get("role"), "bookings"):
            return api_error("Access denied.", 403)

        conn = get_connection()
        cursor = conn.cursor()

        if request.method == "DELETE":
            cursor.execute("SELECT room_id, status FROM bookings WHERE id = ?", (booking_id,))
            bk = cursor.fetchone()
            if not bk:
                conn.close()
                return api_error("Booking not found.", 404)

            if request.args.get("permanent") == "true":
                if bk["status"] not in ["Cancelled"]:
                    conn.close()
                    return api_error("Only Cancelled bookings can be permanently deleted.", 400)
                cursor.execute("DELETE FROM bookings WHERE id = ?", (booking_id,))
                conn.commit()
                conn.close()
                return api_success(message="Reservation record permanently deleted.")
            else:
                cursor.execute("UPDATE bookings SET status = 'Cancelled' WHERE id = ?", (booking_id,))
                if bk["status"] in ["Confirmed", "Checked-in"]:
                    cursor.execute("UPDATE rooms SET status = 'Available' WHERE id = ? AND status IN ('Reserved', 'Occupied')", (bk["room_id"],))
                conn.commit()
                conn.close()
                return api_success(message="Reservation cancelled.")

        if request.method == "PUT":
            data = request.get_json() or {}
            
            cursor.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,))
            bk = cursor.fetchone()
            if not bk:
                conn.close()
                return api_error("Booking not found.", 404)

            # Edit logic
            if "check_in_date" in data:
                # Full edit flow
                room_id = data.get("room_id", bk["room_id"])
                guest_id = data.get("guest_id", bk["guest_id"])
                check_in_date = data.get("check_in_date", bk["check_in_date"])
                check_out_date = data.get("check_out_date", bk["check_out_date"])
                adults = int(data.get("adults", bk.get("adults", 1)))
                children = int(data.get("children", bk.get("children", 0)))
                advance = float(data.get("advance_payment", bk.get("advance_payment", 0.0)))
                discount = float(data.get("discount", bk.get("discount", 0.0)))
                new_status = data.get("status", bk["status"])
                
                try:
                    from datetime import datetime
                    cin = datetime.strptime(check_in_date, "%Y-%m-%d")
                    cout = datetime.strptime(check_out_date, "%Y-%m-%d")
                    nights = (cout - cin).days
                    if nights < 1:
                        conn.close()
                        return api_error("Check-out date must be after check-in date.", 400)
                except Exception:
                    pass

                # Check overlap for the new dates and potentially new room (excluding self)
                if new_status in ["Confirmed", "Checked-in"]:
                    overlap_query = """
                    SELECT id, booking_code, check_in_date, check_out_date FROM bookings
                    WHERE room_id = ? AND id != ?
                      AND status IN ('Confirmed', 'Checked-in')
                      AND NOT (check_out_date <= ? OR check_in_date >= ?)
                    """
                    cursor.execute(overlap_query, (room_id, booking_id, check_in_date, check_out_date))
                    conflict = cursor.fetchone()
                    if conflict:
                        conn.close()
                        return api_error(f"OVERLAP DETECTED! Room is reserved from {conflict['check_in_date']} to {conflict['check_out_date']}.", 409)

                cursor.execute("SELECT price_per_night FROM rooms WHERE id = ?", (room_id,))
                rm = cursor.fetchone()
                room_price = float(rm["price_per_night"]) if rm else float(bk.get("room_price", 0.0))
                subtotal = room_price * nights
                tax_rate = 12.0
                tax_amount = subtotal * (tax_rate / 100.0)
                grand_total = subtotal + tax_amount - discount

                # Restore old room status if changing rooms
                if str(room_id) != str(bk["room_id"]) and bk["status"] in ["Confirmed", "Checked-in"]:
                    cursor.execute("UPDATE rooms SET status = 'Available' WHERE id = ? AND status IN ('Reserved', 'Occupied')", (bk["room_id"],))

                cursor.execute("""
                UPDATE bookings SET 
                    guest_id=?, room_id=?, check_in_date=?, check_out_date=?, 
                    adults=?, children=?, advance_payment=?, discount=?, 
                    room_price=?, tax_amount=?, grand_total=?, status=?
                WHERE id = ?
                """, (guest_id, room_id, check_in_date, check_out_date, adults, children, advance, discount, room_price, tax_amount, grand_total, new_status, booking_id))
                
                # Apply new status logic below

            else:
                # Status-only update flow
                new_status = data.get("status", bk["status"])
                cursor.execute("UPDATE bookings SET status = ? WHERE id = ?", (new_status, booking_id))
            
            # Sync room status for both full edit and status-only
            if new_status == "Cancelled":
                cursor.execute("UPDATE rooms SET status = 'Available' WHERE id = ? AND status = 'Reserved'", (bk["room_id"],))
            elif new_status == "Checked-in":
                cursor.execute("UPDATE rooms SET status = 'Occupied' WHERE id = ?", (bk.get("room_id", data.get("room_id", bk["room_id"])),))
            elif new_status == "Checked-out":
                cursor.execute("UPDATE rooms SET status = 'Cleaning', housekeeping_status = 'Cleaning' WHERE id = ?", (bk.get("room_id", data.get("room_id", bk["room_id"])),))
            elif new_status == "Confirmed":
                # Ensure reserved if available
                cursor.execute("UPDATE rooms SET status = 'Reserved' WHERE id = ? AND status = 'Available'", (bk.get("room_id", data.get("room_id", bk["room_id"])),))

            conn.commit()
            conn.close()
            return api_success(message=f"Booking updated successfully.")
    except Exception as e:
        traceback.print_exc()
        return api_error("Unable to update booking.", 500, error_detail=str(e))


# ==========================================================================
# 5. CHECK-IN & CHECK-OUT WORKFLOWS
# ==========================================================================

@app.route("/api/check-in", methods=["POST"])
def web_check_in():
    try:
        user = get_auth_user()
        if not user or not check_permission(user.get("role"), "checkin"):
            return api_error("Access denied.", 403)

        data = request.get_json() or {}
        room_num = data.get("room_num")
        guest_name = data.get("guest_name")
        nights = data.get("nights", 1)
        phone = data.get("phone", "9999999999")
        email = data.get("email", "")
        id_proof = data.get("id_proof_number", "")

        rooms_dict = load_rooms()
        success, message, invoice = api_check_in(rooms_dict, room_num, guest_name, nights, phone, email, id_proof)

        if not success:
            return api_error(message, 400)

        return api_success({"invoice": invoice, "rooms": load_rooms()}, message=message, status_code=200)
    except Exception as e:
        traceback.print_exc()
        return api_error("Check-in operation failed.", 500, error_detail=str(e))


@app.route("/api/check-out", methods=["POST"])
def web_check_out():
    try:
        user = get_auth_user()
        if not user or not check_permission(user.get("role"), "checkout"):
            return api_error("Access denied.", 403)

        data = request.get_json() or {}
        query = data.get("query") or data.get("room_num")
        services = data.get("services", 0.0)

        rooms_dict = load_rooms()
        success, message, invoice = api_check_out(rooms_dict, query, services)

        if not success:
            return api_error(message, 400)

        return api_success({"invoice": invoice, "rooms": load_rooms()}, message=message, status_code=200)
    except Exception as e:
        traceback.print_exc()
        return api_error("Check-out operation failed.", 500, error_detail=str(e))


# ==========================================================================
# 6. HOTEL SERVICES & BILLING
# ==========================================

@app.route("/api/services", methods=["GET", "POST"])
def handle_services():
    try:
        if request.method == "POST":
            user = get_auth_user()
            if not user or not check_permission(user.get("role"), "services"):
                return api_error("Access denied.", 403)

            data = request.get_json() or {}
            name = data.get("service_name", "").strip()
            category = data.get("category", "Other").strip()
            price = float(data.get("unit_price", 0.0))

            if not name:
                return api_error("Service name is required.", 400)

            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("INSERT INTO services (service_name, category, unit_price) VALUES (?, ?, ?)", (name, category, price))
            conn.commit()
            conn.close()
            return api_success(message=f"Service '{name}' added.", status_code=201)

        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM services ORDER BY category ASC, service_name ASC")
        services = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return api_success({"services": services})
    except Exception as e:
        traceback.print_exc()
        return api_error("Unable to load services.", 500, error_detail=str(e))


@app.route("/api/services/add-to-booking", methods=["POST"])
def add_service_to_booking():
    try:
        user = get_auth_user()
        if not user or not check_permission(user.get("role"), "services"):
            return api_error("Access denied.", 403)

        data = request.get_json() or {}
        booking_id = data.get("booking_id")
        service_name = data.get("service_name")

        if not booking_id or not service_name:
            return api_error("Booking ID and Service Name are required.", 400)

        try:
            booking_id = int(booking_id)
            quantity = int(data.get("quantity", 1))
            unit_price = float(data.get("unit_price", 0.0))
            total_price = quantity * unit_price
        except (ValueError, TypeError):
            return api_error("Invalid booking_id, quantity, or unit_price.", 400)

        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
        INSERT INTO booking_services (booking_id, service_name, quantity, unit_price, total_price, notes)
        VALUES (?, ?, ?, ?, ?, ?)
        """, (booking_id, service_name, quantity, unit_price, total_price, data.get("notes", "")))

        conn.commit()
        conn.close()
        return api_success(message=f"Added ${total_price:.2f} for {service_name}.")
    except Exception as e:
        return api_error("Unable to add service to booking.", 500, error_detail=str(e))


@app.route("/api/services/<int:service_id>", methods=["DELETE"])
def delete_service_item(service_id):
    try:
        user = get_auth_user()
        if not user or not check_permission(user.get("role"), "services"):
            return api_error("Access denied.", 403)
        if normalize_role(user.get("role")) not in ["Admin", "Manager"]:
            return api_error("Admin or Manager role required to remove services.", 403)

        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, service_name FROM services WHERE id = ?", (service_id,))
        row = cursor.fetchone()
        if not row:
            conn.close()
            return api_error("Service not found.", 404)

        cursor.execute("DELETE FROM services WHERE id = ?", (service_id,))
        conn.commit()
        conn.close()
        return api_success(message=f"Service '{row['service_name']}' removed from catalog.")
    except Exception as e:
        return api_error("Unable to remove service.", 500, error_detail=str(e))


@app.route("/api/services/booking-service/<int:item_id>", methods=["DELETE"])
def remove_booking_service(item_id):
    try:
        user = get_auth_user()
        if not user or not check_permission(user.get("role"), "services"):
            return api_error("Access denied.", 403)

        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, service_name, total_price FROM booking_services WHERE id = ?", (item_id,))
        row = cursor.fetchone()
        if not row:
            conn.close()
            return api_error("Booking service item not found.", 404)

        cursor.execute("DELETE FROM booking_services WHERE id = ?", (item_id,))
        conn.commit()
        conn.close()
        return api_success(message=f"Removed service '{row['service_name']}' (${row['total_price']:.2f}) from booking.")
    except Exception as e:
        return api_error("Unable to remove service charge.", 500, error_detail=str(e))


@app.route("/api/invoices/<invoice_id>", methods=["GET"])
def get_invoice(invoice_id):
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
        SELECT i.*, g.full_name as guest_name, g.phone, g.email, g.address, r.room_number, r.room_type, b.check_in_date, b.check_out_date
        FROM invoices i
        JOIN guests g ON i.guest_id = g.id
        JOIN rooms r ON i.room_id = r.id
        JOIN bookings b ON i.booking_id = b.id
        WHERE i.id = ? OR i.invoice_number = ?
        """, (str(invoice_id), str(invoice_id)))
        row = cursor.fetchone()

        if not row:
            conn.close()
            return api_error("Invoice not found.", 404)

        invoice_data = dict(row)

        # Fetch attached services
        cursor.execute("SELECT * FROM booking_services WHERE booking_id = ?", (invoice_data["booking_id"],))
        services_list = [dict(r) for r in cursor.fetchall()]
        invoice_data["services"] = services_list

        conn.close()
        return api_success({"invoice": invoice_data})
    except Exception as e:
        return api_error("Unable to retrieve invoice.", 500, error_detail=str(e))


# ==========================================================================
# 7. PAYMENTS ENDPOINTS
# ==========================================================================
@app.route("/api/payments", methods=["GET", "POST"])
def handle_payments():
    try:
        user = get_auth_user()
        if not user or not check_permission(user.get("role"), "billing"):
            return api_error("Access denied.", 403)

        conn = get_connection()
        cursor = conn.cursor()

        if request.method == "POST":
            data = request.get_json() or {}
            invoice_number = data.get("invoice_number", "").strip()
            amount = float(data.get("amount", 0.0))
            payment_method = data.get("payment_method", "Cash").strip()
            transaction_ref = data.get("transaction_ref", "").strip()

            if not invoice_number or amount <= 0:
                conn.close()
                return api_error("Valid Invoice number and positive amount are required.", 400)

            cursor.execute("SELECT id, booking_id, grand_total, amount_paid, balance_due FROM invoices WHERE invoice_number = ?", (invoice_number,))
            invoice = cursor.fetchone()

            if not invoice:
                conn.close()
                return api_error("Invoice not found.", 404)

            new_amount_paid = float(invoice["amount_paid"]) + amount
            new_balance_due = max(0.0, float(invoice["grand_total"]) - new_amount_paid)
            new_payment_status = "Paid" if new_balance_due <= 0 else "Partial"

            cursor.execute("""
            UPDATE invoices SET 
                amount_paid = ?, 
                balance_due = ?,
                payment_status = ?
            WHERE id = ?
            """, (new_amount_paid, new_balance_due, new_payment_status, invoice["id"]))

            cursor.execute("""
            INSERT INTO payments (invoice_number, booking_id, amount, payment_method, transaction_ref)
            VALUES (?, ?, ?, ?, ?)
            """, (invoice_number, invoice["booking_id"], amount, payment_method, transaction_ref))
            
            conn.commit()
            conn.close()
            
            return api_success(message=f"Payment of ${amount:.2f} applied to {invoice_number}.", status_code=201)

        invoice_num = request.args.get("invoice_number")
        if invoice_num:
            cursor.execute("SELECT * FROM payments WHERE invoice_number = ? ORDER BY id DESC", (invoice_num,))
        else:
            cursor.execute("SELECT * FROM payments ORDER BY id DESC LIMIT 100")
            
        payments = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return api_success({"payments": payments})

    except Exception as e:
        traceback.print_exc()
        return api_error("Unable to process payments.", 500, error_detail=str(e))


# ==========================================================================
# 8. HOUSEKEEPING ENDPOINTS
# ==========================================================================

@app.route("/api/housekeeping", methods=["GET", "POST", "PUT"])
def handle_housekeeping():
    try:
        user = get_auth_user()
        if not user or not check_permission(user.get("role"), "housekeeping"):
            return api_error("Access denied.", 403)

        conn = get_connection()
        cursor = conn.cursor()

        if request.method in ["PUT", "POST"]:
            data = request.get_json() or {}
            r_num = str(data.get("room_number", "")).strip()
            status = data.get("cleaning_status", "Clean")
            staff = data.get("assigned_staff", "Housekeeping Staff")
            notes = data.get("notes", "")

            if not r_num:
                conn.close()
                return api_error("Room number is required.", 400)

            # Synchronize room status with housekeeping status
            if status in ["Clean", "Inspected"]:
                # If room was in Cleaning or Maintenance, transition to Available (unless active booking)
                cursor.execute("SELECT status FROM rooms WHERE room_number = ?", (r_num,))
                curr_room = cursor.fetchone()
                if curr_room and curr_room["status"] in ["Cleaning", "Maintenance"]:
                    cursor.execute("UPDATE rooms SET status = 'Available', housekeeping_status = ? WHERE room_number = ?", (status, r_num))
                else:
                    cursor.execute("UPDATE rooms SET housekeeping_status = ? WHERE room_number = ?", (status, r_num))
            elif status == "Maintenance":
                cursor.execute("UPDATE rooms SET status = 'Maintenance', housekeeping_status = 'Maintenance' WHERE room_number = ?", (r_num,))
            elif status in ["Dirty", "Cleaning"]:
                cursor.execute("SELECT status FROM rooms WHERE room_number = ?", (r_num,))
                curr_room = cursor.fetchone()
                if curr_room and curr_room["status"] not in ["Occupied", "Reserved"]:
                    cursor.execute("UPDATE rooms SET status = 'Cleaning', housekeeping_status = ? WHERE room_number = ?", (status, r_num))
                else:
                    cursor.execute("UPDATE rooms SET housekeeping_status = ? WHERE room_number = ?", (status, r_num))
            else:
                cursor.execute("UPDATE rooms SET housekeeping_status = ? WHERE room_number = ?", (status, r_num))

            # Upsert into housekeeping table
            cursor.execute("""
            INSERT INTO housekeeping (room_number, cleaning_status, assigned_staff, notes)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (room_number) DO UPDATE SET 
                cleaning_status = excluded.cleaning_status,
                assigned_staff = excluded.assigned_staff,
                notes = excluded.notes,
                last_updated = CURRENT_TIMESTAMP
            """, (r_num, status, staff, notes))

            conn.commit()
            conn.close()
            return api_success(message=f"Housekeeping status for Room {r_num} updated to {status}.")

        cursor.execute("""
        SELECT r.room_number, r.room_type, r.floor, r.status as room_status, r.housekeeping_status, h.assigned_staff, h.notes, h.last_updated
        FROM rooms r
        LEFT JOIN housekeeping h ON r.room_number = h.room_number
        ORDER BY r.room_number ASC
        """)
        housekeeping_list = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return api_success({"housekeeping": housekeeping_list})
    except Exception as e:
        traceback.print_exc()
        return api_error("Unable to process housekeeping request.", 500, error_detail=str(e))


# ==========================================================================
# 8. MAINTENANCE ENDPOINTS
# ==========================================================================

@app.route("/api/maintenance", methods=["GET", "POST", "PUT"])
def handle_maintenance():
    try:
        user = get_auth_user()
        if not user:
            return api_error("Authentication required.", 401)

        conn = get_connection()
        cursor = conn.cursor()

        if request.method == "POST":
            data = request.get_json() or {}
            r_num = str(data.get("room_number", "")).strip()
            category = data.get("issue_category", "General")
            priority = data.get("priority", "Medium")
            desc = data.get("description", "")
            assigned = data.get("assigned_staff", "")
            reported_by = user.get("username", "Staff")

            if not r_num:
                conn.close()
                return api_error("Room number is required.", 400)

            success, msg, log_id = log_room_maintenance(r_num, category, priority, desc, reported_by, assigned)
            conn.close()
            if not success:
                return api_error(msg, 400)
            return api_success({"id": log_id}, message=msg)

        elif request.method == "PUT":
            data = request.get_json() or {}
            log_id = data.get("id")
            new_status = data.get("status")

            if not log_id:
                conn.close()
                return api_error("Maintenance log ID is required.", 400)

            if new_status == "Resolved":
                success, msg = resolve_room_maintenance(log_id)
                conn.close()
                if not success:
                    return api_error(msg, 400)
                return api_success(message=msg)
            else:
                assigned = data.get("assigned_staff")
                cursor.execute("""
                UPDATE maintenance_logs
                SET status = COALESCE(?, status),
                    assigned_staff = COALESCE(?, assigned_staff),
                    priority = COALESCE(?, priority)
                WHERE id = ?
                """, (new_status, assigned, data.get("priority"), log_id))
                conn.commit()
                conn.close()
                return api_success(message="Maintenance log updated.")

        else:
            status_filter = request.args.get("status")
            room_filter = request.args.get("room_number")

            query = "SELECT * FROM maintenance_logs"
            params = []
            conditions = []
            if status_filter:
                conditions.append("status = ?")
                params.append(status_filter)
            if room_filter:
                conditions.append("room_number = ?")
                params.append(room_filter)

            if conditions:
                query += " WHERE " + " AND ".join(conditions)
            query += " ORDER BY id DESC"

            cursor.execute(query, params)
            logs = [dict(row) for row in cursor.fetchall()]

            cursor.execute("SELECT COUNT(*) as count FROM maintenance_logs WHERE status IN ('Open', 'In Progress')")
            active_count = cursor.fetchone()["count"]
            cursor.execute("SELECT COUNT(*) as count FROM maintenance_logs WHERE status = 'Resolved'")
            resolved_count = cursor.fetchone()["count"]

            conn.close()
            return api_success({
                "maintenance_logs": logs,
                "stats": {
                    "active": active_count,
                    "resolved": resolved_count,
                    "total": len(logs)
                }
            })
    except Exception as e:
        traceback.print_exc()
        return api_error("Unable to process maintenance request.", 500, error_detail=str(e))


# ==========================================================================
# 9. DASHBOARD & REPORTS ENDPOINTS
# ==========================================================================

@app.route("/api/dashboard", methods=["GET"])
def get_dashboard():
    try:
        stats = api_get_stats()

        conn = get_connection()
        cursor = conn.cursor()

        # Active check-ins
        cursor.execute("""
        SELECT b.*, g.full_name as guest_name, r.room_number, r.room_type
        FROM bookings b 
        JOIN guests g ON b.guest_id = g.id 
        JOIN rooms r ON b.room_id = r.id 
        WHERE b.status = 'Checked-in'
        ORDER BY b.id DESC
        """)
        active_checkins = [dict(row) for row in cursor.fetchall()]

        conn.close()
        return api_success({
            "stats": stats,
            "active_checkins": active_checkins,
            "database_engine": get_database_type()
        })
    except Exception as e:
        traceback.print_exc()
        return api_error("Unable to load dashboard statistics.", 500, error_detail=str(e))


@app.route("/api/reports/export/csv", methods=["GET"])
def export_csv():
    try:
        report_type = request.args.get("type", "guests").lower()
        start_date = request.args.get("start_date", "").strip()
        end_date = request.args.get("end_date", "").strip()

        conn = get_connection()
        cursor = conn.cursor()

        output = io.StringIO()
        writer = csv.writer(output)

        if report_type in ["revenue", "invoices"]:
            query = """
            SELECT i.invoice_number, i.booking_id, g.full_name as guest_name, r.room_number,
                   i.room_charges, i.service_charges, i.tax_amount, i.discount, i.grand_total,
                   i.advance_paid, i.amount_paid, i.balance_due, i.payment_status, i.issue_date
            FROM invoices i
            LEFT JOIN guests g ON i.guest_id = g.id
            LEFT JOIN rooms r ON i.room_id = r.id
            """
            params = []
            conditions = []
            if start_date:
                conditions.append("i.issue_date >= ?")
                params.append(f"{start_date} 00:00:00")
            if end_date:
                conditions.append("i.issue_date <= ?")
                params.append(f"{end_date} 23:59:59")
            if conditions:
                query += " WHERE " + " AND ".join(conditions)
            query += " ORDER BY i.id DESC"
            cursor.execute(query, tuple(params))
            rows = cursor.fetchall()
            writer.writerow(["Invoice Number", "Room", "Guest Name", "Room Charges", "Service Charges", "Tax", "Discount", "Grand Total", "Advance Paid", "Amount Paid", "Balance Due", "Status", "Date"])
            for r in rows:
                writer.writerow([
                    r["invoice_number"], r["room_number"], r["guest_name"],
                    r["room_charges"], r["service_charges"], r["tax_amount"], r["discount"],
                    r["grand_total"], r["advance_paid"], r["amount_paid"], r["balance_due"],
                    r["payment_status"], r["issue_date"]
                ])

        elif report_type in ["checkin", "checkout", "stays"]:
            query = """
            SELECT b.booking_code, g.full_name as guest_name, g.phone, r.room_number, r.room_type,
                   b.check_in_date, b.check_out_date, b.status, b.room_price, b.grand_total, b.advance_payment
            FROM bookings b
            JOIN guests g ON b.guest_id = g.id
            JOIN rooms r ON b.room_id = r.id
            """
            params = []
            conditions = []
            if report_type == "checkin":
                conditions.append("b.status IN ('Checked-in', 'Confirmed')")
            elif report_type == "checkout":
                conditions.append("b.status = 'Checked-out'")
            if start_date:
                conditions.append("b.check_in_date >= ?")
                params.append(start_date)
            if end_date:
                conditions.append("b.check_out_date <= ?")
                params.append(end_date)
            if conditions:
                query += " WHERE " + " AND ".join(conditions)
            query += " ORDER BY b.id DESC"
            cursor.execute(query, tuple(params))
            rows = cursor.fetchall()
            writer.writerow(["Booking Code", "Guest Name", "Phone", "Room", "Type", "Check-In", "Check-Out", "Status", "Room Price", "Grand Total", "Advance"])
            for r in rows:
                writer.writerow([
                    r["booking_code"], r["guest_name"], r["phone"], r["room_number"],
                    r["room_type"], r["check_in_date"], r["check_out_date"], r["status"],
                    r["room_price"], r["grand_total"], r["advance_payment"]
                ])

        elif report_type == "bookings":
            query = """
            SELECT b.*, g.full_name as guest_name, r.room_number, r.room_type
            FROM bookings b
            JOIN guests g ON b.guest_id = g.id
            JOIN rooms r ON b.room_id = r.id
            """
            params = []
            conditions = []
            if start_date:
                conditions.append("b.check_in_date >= ?")
                params.append(start_date)
            if end_date:
                conditions.append("b.check_out_date <= ?")
                params.append(end_date)
            if conditions:
                query += " WHERE " + " AND ".join(conditions)
            query += " ORDER BY b.id DESC"
            cursor.execute(query, tuple(params))
            rows = cursor.fetchall()
            writer.writerow(["ID", "Code", "Guest Name", "Room", "Type", "Check-In", "Check-Out", "Adults", "Children", "Status", "Advance", "Grand Total"])
            for r in rows:
                writer.writerow([
                    r["id"], r["booking_code"], r["guest_name"], r["room_number"],
                    r["room_type"], r["check_in_date"], r["check_out_date"],
                    r["adults"], r["children"], r["status"], r["advance_payment"], r["grand_total"]
                ])

        elif report_type in ["occupancy", "rooms"]:
            cursor.execute("SELECT * FROM rooms ORDER BY room_number ASC")
            rows = cursor.fetchall()
            writer.writerow(["ID", "Room Number", "Type", "Price", "Front Desk Status", "Housekeeping Status", "Floor", "Capacity"])
            for r in rows:
                writer.writerow([
                    r["id"], r["room_number"], r["room_type"], r["price_per_night"],
                    r["status"], r["housekeeping_status"], r["floor"], r["capacity"]
                ])

        else:
            cursor.execute("SELECT * FROM guests ORDER BY id DESC")
            rows = cursor.fetchall()
            writer.writerow(["ID", "Full Name", "Phone", "Email", "City", "Country", "ID Proof", "ID Number"])
            for r in rows:
                writer.writerow([
                    r["id"], r["full_name"], r["phone"], r["email"],
                    r["city"], r["country"], r["id_proof_type"], r["id_proof_number"]
                ])

        conn.close()
        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={"Content-disposition": f"attachment; filename=hotel_{report_type}_report.csv"}
        )
    except Exception as e:
        traceback.print_exc()
        return api_error("Unable to export CSV report.", 500, error_detail=str(e))


# Local Dev Entry Point
if __name__ == "__main__":
    print(f"\n🚀 Starting Grand Horizon Hotel Enterprise Flask Server ({get_database_type()})...")
    print("📍 Local URL:   http://127.0.0.1:5000")
    print("📍 Network URL: http://0.0.0.0:5000\n")
    app.run(host="0.0.0.0", port=5000, debug=True)
