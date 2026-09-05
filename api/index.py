"""
api/index.py
------------
Enterprise REST API Engine for Grand Horizon Hotel Management System.
Features RBAC Authorization, Overlap-Checked Bookings, Guest Profiles,
Housekeeping Management, Itemized Invoicing, and Vercel Serverless Function compatibility.
"""

import os
import sys
import csv
import io
from datetime import datetime

# Ensure root directory is in Python path for database & auth modules
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from flask import Flask, jsonify, request, send_from_directory, Response
from flask_cors import CORS

from database import get_connection, hash_password
from auth import authenticate_user, get_current_user, check_permission, logout_user
from hotel_manager import load_rooms, api_check_in, api_check_out, api_get_stats

app = Flask(__name__, static_folder=parent_dir, static_url_path="")
CORS(app)


# Helper: Extract token from Authorization header or query param
def get_auth_user():
    auth_header = request.headers.get("Authorization", "")
    token = ""
    if auth_header.startswith("Bearer "):
        token = auth_header.split(" ")[1]
    elif "token" in request.args:
        token = request.args.get("token")
    return get_current_user(token)


# Static Front-End Routing
@app.route("/")
def serve_index():
    return send_from_directory(parent_dir, "index.html")


@app.route("/<path:path>")
def serve_static(path):
    if os.path.exists(os.path.join(parent_dir, path)):
        return send_from_directory(parent_dir, path)
    return send_from_directory(parent_dir, "index.html")


# ==========================================
# 1. AUTHENTICATION & RBAC ENDPOINTS
# ==========================================

@app.route("/api/auth/login", methods=["POST"])
def login():
    data = request.get_json() or {}
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()

    if not username or not password:
        return jsonify({"success": False, "message": "Username and password required."}), 400

    success, msg, session_data = authenticate_user(username, password)
    if not success:
        return jsonify({"success": False, "message": msg}), 401

    return jsonify({"success": True, "message": msg, "user": session_data})


@app.route("/api/auth/me", methods=["GET"])
def get_me():
    user = get_auth_user()
    if not user:
        return jsonify({"success": False, "message": "Unauthorized"}), 401
    return jsonify({"success": True, "user": user})


@app.route("/api/auth/logout", methods=["POST"])
def logout():
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        logout_user(auth_header.split(" ")[1])
    return jsonify({"success": True, "message": "Logged out."})


@app.route("/api/auth/users", methods=["GET", "POST"])
def manage_users():
    user = get_auth_user()
    if not user or user["role"] != "Admin":
        return jsonify({"success": False, "message": "Admin authorization required."}), 403

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
            return jsonify({"success": False, "message": "All fields required."}), 400

        try:
            pwd_hash = hash_password(password)
            cursor.execute("INSERT INTO users (username, password_hash, full_name, role) VALUES (?, ?, ?, ?)",
                           (username, pwd_hash, full_name, role))
            conn.commit()
            conn.close()
            return jsonify({"success": True, "message": f"Staff user '{username}' created."})
        except Exception as e:
            conn.close()
            return jsonify({"success": False, "message": f"Error: {e}"}), 400

    cursor.execute("SELECT id, username, full_name, role, created_at FROM users ORDER BY id ASC")
    users = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return jsonify({"success": True, "users": users})


# ==========================================
# 2. GUEST MANAGEMENT ENDPOINTS
# ==========================================

@app.route("/api/guests", methods=["GET", "POST"])
def handle_guests():
    user = get_auth_user()
    if not user or not check_permission(user["role"], "guests"):
        return jsonify({"success": False, "message": "Access denied."}), 403

    conn = get_connection()
    cursor = conn.cursor()

    if request.method == "POST":
        data = request.get_json() or {}
        full_name = data.get("full_name", "").strip()
        phone = data.get("phone", "").strip()

        if not full_name or not phone:
            conn.close()
            return jsonify({"success": False, "message": "Guest Full Name and Phone are required."}), 400

        dob = data.get("dob")
        age = data.get("age", 25)
        gender = data.get("gender", "Other")
        email = data.get("email", "")
        address = data.get("address", "")
        city = data.get("city", "")
        state = data.get("state", "")
        country = data.get("country", "India")
        nationality = data.get("nationality", "Indian")
        id_type = data.get("id_proof_type", "Aadhaar / Passport")
        id_num = data.get("id_proof_number", "")
        emergency_name = data.get("emergency_name", "")
        emergency_phone = data.get("emergency_phone", "")
        adults = data.get("adults", 1)
        children = data.get("children", 0)
        special_req = data.get("special_requests", "")
        notes = data.get("notes", "")

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
        return jsonify({"success": True, "message": "Guest added successfully.", "guest_id": guest_id})

    # GET Query logic
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
    return jsonify({"success": True, "guests": guests})


@app.route("/api/guests/<int:guest_id>", methods=["GET", "PUT", "DELETE"])
def handle_single_guest(guest_id):
    user = get_auth_user()
    if not user or not check_permission(user["role"], "guests"):
        return jsonify({"success": False, "message": "Access denied."}), 403

    conn = get_connection()
    cursor = conn.cursor()

    if request.method == "DELETE":
        if user["role"] not in ["Admin", "Manager"]:
            conn.close()
            return jsonify({"success": False, "message": "Delete permission denied."}), 403
        cursor.execute("DELETE FROM guests WHERE id = ?", (guest_id,))
        conn.commit()
        conn.close()
        return jsonify({"success": True, "message": "Guest record deleted."})

    if request.method == "PUT":
        data = request.get_json() or {}
        cursor.execute("""
        UPDATE guests SET 
            full_name = ?, phone = ?, email = ?, address = ?, city = ?, country = ?,
            id_proof_type = ?, id_proof_number = ?, emergency_name = ?, emergency_phone = ?,
            special_requests = ?, notes = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """, (
            data.get("full_name"), data.get("phone"), data.get("email"), data.get("address"),
            data.get("city"), data.get("country"), data.get("id_proof_type"), data.get("id_proof_number"),
            data.get("emergency_name"), data.get("emergency_phone"), data.get("special_requests"),
            data.get("notes"), guest_id
        ))
        conn.commit()
        conn.close()
        return jsonify({"success": True, "message": "Guest updated successfully."})

    # GET details with booking & payment history
    cursor.execute("SELECT * FROM guests WHERE id = ?", (guest_id,))
    guest_row = cursor.fetchone()
    if not guest_row:
        conn.close()
        return jsonify({"success": False, "message": "Guest not found."}), 404

    guest_dict = dict(guest_row)

    # Fetch booking history
    cursor.execute("""
    SELECT b.*, r.room_number, r.room_type 
    FROM bookings b 
    JOIN rooms r ON b.room_id = r.id 
    WHERE b.guest_id = ? 
    ORDER BY b.id DESC
    """, (guest_id,))
    bookings = [dict(row) for row in cursor.fetchall()]

    # Fetch payment history
    cursor.execute("""
    SELECT p.*, i.grand_total 
    FROM payments p 
    JOIN invoices i ON p.booking_id = i.booking_id 
    WHERE i.guest_id = ? 
    ORDER BY p.id DESC
    """, (guest_id,))
    payments = [dict(row) for row in cursor.fetchall()]

    conn.close()
    return jsonify({"success": True, "guest": guest_dict, "bookings": bookings, "payments": payments})


# ==========================================
# 3. ROOM MANAGEMENT ENDPOINTS
# ==========================================

@app.route("/api/rooms", methods=["GET", "POST"])
def handle_rooms():
    conn = get_connection()
    cursor = conn.cursor()

    if request.method == "POST":
        user = get_auth_user()
        if not user or not check_permission(user["role"], "rooms"):
            conn.close()
            return jsonify({"success": False, "message": "Access denied."}), 403

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

        try:
            cursor.execute("""
            INSERT INTO rooms (room_number, floor, room_type, bed_type, capacity, price_per_night, ac_type, amenities, description)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (r_num, floor, r_type, bed_type, capacity, price, ac_type, amenities, desc))

            # Add to housekeeping
            cursor.execute("INSERT OR IGNORE INTO housekeeping (room_number, cleaning_status) VALUES (?, 'Clean')", (r_num,))
            conn.commit()
            conn.close()
            return jsonify({"success": True, "message": f"Room {r_num} added."})
        except Exception as e:
            conn.close()
            return jsonify({"success": False, "message": f"Room creation error: {e}"}), 400

    # GET logic with filters
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
    
    # Format backward-compatible rooms dictionary
    rooms_dict = {}
    for r in rooms_list:
        rooms_dict[r["room_number"]] = {
            "id": r["id"],
            "type": r["room_type"],
            "price": r["price_per_night"],
            "status": r["status"],
            "guest": r["guest"],
            "housekeeping_status": r["housekeeping_status"],
            "floor": r["floor"],
            "capacity": r["capacity"],
            "amenities": r["amenities"],
            "active_booking_id": r["active_booking_id"]
        }

    return jsonify({"success": True, "rooms": rooms_dict, "list": rooms_list})


@app.route("/api/rooms/<int:room_id>", methods=["PUT", "DELETE"])
def handle_single_room(room_id):
    user = get_auth_user()
    if not user or not check_permission(user["role"], "rooms"):
        return jsonify({"success": False, "message": "Access denied."}), 403

    conn = get_connection()
    cursor = conn.cursor()

    if request.method == "DELETE":
        cursor.execute("DELETE FROM rooms WHERE id = ?", (room_id,))
        conn.commit()
        conn.close()
        return jsonify({"success": True, "message": "Room deleted."})

    if request.method == "PUT":
        data = request.get_json() or {}
        cursor.execute("""
        UPDATE rooms SET 
            room_type = ?, price_per_night = ?, status = ?, housekeeping_status = ?,
            amenities = ?, capacity = ?
        WHERE id = ?
        """, (
            data.get("room_type"), data.get("price_per_night"), data.get("status"),
            data.get("housekeeping_status"), data.get("amenities"), data.get("capacity"), room_id
        ))
        conn.commit()
        conn.close()
        return jsonify({"success": True, "message": "Room updated."})


# ==========================================
# 4. RESERVATION & OVERLAP-CHECKED BOOKINGS
# ==========================================

@app.route("/api/bookings", methods=["GET", "POST"])
def handle_bookings():
    user = get_auth_user()
    if not user or not check_permission(user["role"], "bookings"):
        return jsonify({"success": False, "message": "Access denied."}), 403

    conn = get_connection()
    cursor = conn.cursor()

    if request.method == "POST":
        data = request.get_json() or {}
        guest_id = data.get("guest_id")
        room_id = data.get("room_id")
        check_in_date = data.get("check_in_date")
        check_out_date = data.get("check_out_date")
        advance = float(data.get("advance_payment", 0.0))
        source = data.get("booking_source", "Direct Website")

        if not guest_id or not room_id or not check_in_date or not check_out_date:
            conn.close()
            return jsonify({"success": False, "message": "Guest, Room, Check-in and Check-out dates are required."}), 400

        # CRITICAL OVERLAP PREVENTION QUERY
        # Checks if room has an existing Confirmed or Checked-in booking during check_in_date -> check_out_date
        overlap_query = """
        SELECT id FROM bookings
        WHERE room_id = ? 
          AND status IN ('Confirmed', 'Checked-in')
          AND NOT (check_out_date <= ? OR check_in_date >= ?)
        """
        cursor.execute(overlap_query, (room_id, check_in_date, check_out_date))
        if cursor.fetchone():
            conn.close()
            return jsonify({
                "success": False, 
                "message": "OVERLAP DETECTED! This room is already reserved/occupied for the selected dates."
            }), 409

        booking_code = f"RES-{int(os.urandom(3).hex(), 16)}"
        cursor.execute("""
        INSERT INTO bookings (booking_code, guest_id, room_id, check_in_date, check_out_date, booking_source, advance_payment, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'Confirmed')
        """, (booking_code, guest_id, room_id, check_in_date, check_out_date, source, advance))
        
        # Update room status to Reserved if starting today
        cursor.execute("UPDATE rooms SET status = 'Reserved' WHERE id = ? AND status = 'Available'", (room_id,))

        conn.commit()
        conn.close()
        return jsonify({"success": True, "message": f"Reservation {booking_code} confirmed successfully!"})

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
    return jsonify({"success": True, "bookings": bookings})


# ==========================================
# 5. CHECK-IN & CHECK-OUT WORKFLOWS
# ==========================================

@app.route("/api/check-in", methods=["POST"])
def web_check_in():
    data = request.get_json() or {}
    room_num = data.get("room_num")
    guest_name = data.get("guest_name")
    nights = data.get("nights", 1)

    rooms_dict = load_rooms()
    success, message, invoice = api_check_in(rooms_dict, room_num, guest_name, nights)

    if not success:
        return jsonify({"success": False, "message": message}), 400

    return jsonify({"success": True, "message": message, "invoice": invoice, "rooms": load_rooms()})


@app.route("/api/check-out", methods=["POST"])
def web_check_out():
    data = request.get_json() or {}
    query = data.get("query") or data.get("room_num")
    services = data.get("services", 0.0)

    rooms_dict = load_rooms()
    success, message, invoice = api_check_out(rooms_dict, query, services)

    if not success:
        return jsonify({"success": False, "message": message}), 400

    return jsonify({"success": True, "message": message, "invoice": invoice, "rooms": load_rooms()})


# ==========================================
# 6. HOTEL SERVICES & BILLING ENDPOINTS
# ==========================================

@app.route("/api/services", methods=["GET"])
def get_services():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM services ORDER BY category ASC")
    services = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return jsonify({"success": True, "services": services})


@app.route("/api/services/add-to-booking", methods=["POST"])
def add_service_to_booking():
    user = get_auth_user()
    if not user or not check_permission(user["role"], "services"):
        return jsonify({"success": False, "message": "Access denied."}), 403

    data = request.get_json() or {}
    booking_id = data.get("booking_id")
    service_name = data.get("service_name")
    quantity = int(data.get("quantity", 1))
    unit_price = float(data.get("unit_price", 0.0))
    total_price = quantity * unit_price

    if not booking_id or not service_name:
        return jsonify({"success": False, "message": "Booking ID and Service Name required."}), 400

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO booking_services (booking_id, service_name, quantity, unit_price, total_price, notes)
    VALUES (?, ?, ?, ?, ?, ?)
    """, (booking_id, service_name, quantity, unit_price, total_price, data.get("notes", "")))

    conn.commit()
    conn.close()
    return jsonify({"success": True, "message": f"Added ${total_price} for {service_name}."})


@app.route("/api/invoices/<int:invoice_id>", methods=["GET"])
def get_invoice(invoice_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT i.*, g.full_name as guest_name, g.phone, g.email, g.address, r.room_number, r.room_type, b.check_in_date, b.check_out_date
    FROM invoices i
    JOIN guests g ON i.guest_id = g.id
    JOIN rooms r ON i.room_id = r.id
    JOIN bookings b ON i.booking_id = b.id
    WHERE i.id = ? OR i.invoice_number = ?
    """, (invoice_id, str(invoice_id)))
    row = cursor.fetchone()
    conn.close()

    if not row:
        return jsonify({"success": False, "message": "Invoice not found."}), 404

    return jsonify({"success": True, "invoice": dict(row)})


# ==========================================
# 7. HOUSEKEEPING ENDPOINTS
# ==========================================

@app.route("/api/housekeeping", methods=["GET", "PUT"])
def handle_housekeeping():
    user = get_auth_user()
    if not user or not check_permission(user["role"], "housekeeping"):
        return jsonify({"success": False, "message": "Access denied."}), 403

    conn = get_connection()
    cursor = conn.cursor()

    if request.method == "PUT":
        data = request.get_json() or {}
        r_num = data.get("room_number")
        status = data.get("cleaning_status", "Clean")
        staff = data.get("assigned_staff", "Housekeeping Staff")
        notes = data.get("notes", "")

        cursor.execute("UPDATE rooms SET housekeeping_status = ? WHERE room_number = ?", (status, r_num))
        cursor.execute("""
        INSERT INTO housekeeping (room_number, cleaning_status, assigned_staff, notes)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(room_number) DO UPDATE SET 
            cleaning_status = excluded.cleaning_status,
            assigned_staff = excluded.assigned_staff,
            notes = excluded.notes,
            last_updated = CURRENT_TIMESTAMP
        """, (r_num, status, staff, notes))

        conn.commit()
        conn.close()
        return jsonify({"success": True, "message": f"Housekeeping for Room {r_num} set to {status}."})

    cursor.execute("""
    SELECT r.room_number, r.room_type, r.floor, r.status as room_status, r.housekeeping_status, h.assigned_staff, h.notes, h.last_updated
    FROM rooms r
    LEFT JOIN housekeeping h ON r.room_number = h.room_number
    ORDER BY r.room_number ASC
    """)
    housekeeping_list = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return jsonify({"success": True, "housekeeping": housekeeping_list})


# ==========================================
# 8. DASHBOARD & REPORTS ENDPOINTS
# ==========================================

@app.route("/api/dashboard", methods=["GET"])
def get_dashboard():
    rooms_dict = load_rooms()
    stats = api_get_stats(rooms_dict)

    conn = get_connection()
    cursor = conn.cursor()

    # Today's check-ins
    cursor.execute("""
    SELECT b.*, g.full_name as guest_name, r.room_number 
    FROM bookings b 
    JOIN guests g ON b.guest_id = g.id 
    JOIN rooms r ON b.room_id = r.id 
    WHERE b.status = 'Checked-in'
    """)
    today_checkins = [dict(row) for row in cursor.fetchall()]

    conn.close()
    return jsonify({
        "success": True,
        "stats": stats,
        "active_checkins": today_checkins
    })


@app.route("/api/reports/export/csv", methods=["GET"])
def export_csv():
    report_type = request.args.get("type", "guests")
    conn = get_connection()
    cursor = conn.cursor()

    output = io.StringIO()
    writer = csv.writer(output)

    if report_type == "bookings":
        cursor.execute("SELECT * FROM bookings")
        rows = cursor.fetchall()
        writer.writerow(["ID", "Code", "Guest ID", "Room ID", "Check-In", "Check-Out", "Status", "Advance"])
        for r in rows:
            writer.writerow([r["id"], r["booking_code"], r["guest_id"], r["room_id"], r["check_in_date"], r["check_out_date"], r["status"], r["advance_payment"]])
    else:
        cursor.execute("SELECT * FROM guests")
        rows = cursor.fetchall()
        writer.writerow(["ID", "Full Name", "Phone", "Email", "City", "Country", "ID Proof", "ID Number"])
        for r in rows:
            writer.writerow([r["id"], r["full_name"], r["phone"], r["email"], r["city"], r["country"], r["id_proof_type"], r["id_proof_number"]])

    conn.close()
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-disposition": f"attachment; filename=hotel_{report_type}_report.csv"}
    )


# Local Dev Entry Point
if __name__ == "__main__":
    print("\n🚀 Starting Grand Horizon Hotel Enterprise Flask Server...")
    print("📍 URL: http://127.0.0.1:5000\n")
    app.run(host="127.0.0.1", port=5000, debug=True)
