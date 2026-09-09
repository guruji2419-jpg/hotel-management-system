"""
hotel_manager.py
----------------
Core domain logic and data structures for the Grand Horizon Hotel Management System.
Bridges database operations with CLI terminal interface (main.py)
and non-interactive API helpers for the Flask backend (api/index.py).
"""

import os
import secrets
from datetime import datetime, date
from database import get_connection

# Default initial room data structure fallback
INITIAL_ROOMS = {
    "101": {"id": 1, "type": "Standard", "price": 50.0, "status": "Available", "guest": None, "nights": 0, "services": 0.0, "housekeeping_status": "Clean", "floor": 1, "capacity": 1, "amenities": "WiFi, TV"},
    "102": {"id": 2, "type": "Standard", "price": 50.0, "status": "Available", "guest": None, "nights": 0, "services": 0.0, "housekeeping_status": "Clean", "floor": 1, "capacity": 2, "amenities": "WiFi, TV"},
    "103": {"id": 3, "type": "Deluxe",   "price": 80.0, "status": "Available", "guest": None, "nights": 0, "services": 0.0, "housekeeping_status": "Clean", "floor": 1, "capacity": 2, "amenities": "WiFi, TV, Mini-bar"},
    "201": {"id": 4, "type": "Deluxe",   "price": 80.0, "status": "Available", "guest": None, "nights": 0, "services": 0.0, "housekeeping_status": "Clean", "floor": 2, "capacity": 2, "amenities": "WiFi, TV, Balcony"},
    "202": {"id": 5, "type": "Suite",    "price": 150.0, "status": "Available", "guest": None, "nights": 0, "services": 0.0, "housekeeping_status": "Clean", "floor": 2, "capacity": 4, "amenities": "WiFi, TV, Jacuzzi, Living Room"},
}


def get_current_date_str():
    """Returns today's date in standard ISO YYYY-MM-DD format."""
    return datetime.now().strftime("%Y-%m-%d")


def load_rooms():
    """Loads current room states and active guest stays directly from the database."""
    rooms_dict = {}
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        # Query all rooms with active booking details if occupied
        query = """
        SELECT 
            r.id, r.room_number, r.floor, r.room_type, r.bed_type, r.capacity,
            r.price_per_night, r.ac_type, r.amenities, r.description,
            r.status, r.housekeeping_status,
            g.full_name as guest, b.check_in_date, b.check_out_date, b.id as active_booking_id
        FROM rooms r
        LEFT JOIN bookings b ON r.id = b.room_id AND b.status = 'Checked-in'
        LEFT JOIN guests g ON b.guest_id = g.id
        ORDER BY r.room_number ASC
        """
        cursor.execute(query)
        rows = cursor.fetchall()
        conn.close()

        if rows:
            for row in rows:
                r_num = str(row["room_number"])
                rooms_dict[r_num] = {
                    "id": row["id"],
                    "type": row["room_type"],
                    "price": float(row["price_per_night"]),
                    "status": row["status"],
                    "housekeeping_status": row.get("housekeeping_status", "Clean"),
                    "floor": row.get("floor", 1),
                    "capacity": row.get("capacity", 2),
                    "amenities": row.get("amenities", ""),
                    "guest": row["guest"] if row["guest"] else None,
                    "active_booking_id": row.get("active_booking_id"),
                    "check_in_date": row.get("check_in_date"),
                    "check_out_date": row.get("check_out_date"),
                    "nights": 1,
                    "services": 0.0
                }
            return rooms_dict
    except Exception as e:
        print(f"⚠️ [HOTEL_MANAGER] DB Load warning: {e}. Using fallback rooms.")
        
    return INITIAL_ROOMS.copy()


def save_rooms(rooms):
    """Syncs in-memory room status changes back to the database."""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        for r_num, info in rooms.items():
            cursor.execute("UPDATE rooms SET status = ? WHERE room_number = ?", (info["status"], str(r_num)))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"❌ [HOTEL_MANAGER] DB Sync error: {e}")


# ==========================================================================
# NON-INTERACTIVE API HELPER FUNCTIONS
# ==========================================================================

def api_check_in(rooms, room_num, guest_name, nights=1, phone="9999999999", email="", id_proof_number=""):
    """API non-interactive helper to check in a guest."""
    room_num = str(room_num).strip()
    guest_name = str(guest_name).strip()
    
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT id, room_number, room_type, price_per_night, status FROM rooms WHERE room_number = ?", (room_num,))
    room = cursor.fetchone()

    if not room:
        conn.close()
        return False, f"Room {room_num} does not exist.", None

    if room["status"] == "Occupied":
        conn.close()
        return False, f"Room {room_num} is currently Occupied.", None

    if room["status"] == "Cleaning" or room.get("housekeeping_status") == "Cleaning":
        conn.close()
        return False, f"Room {room_num} is currently being cleaned. Check-in not allowed.", None

    if room["status"] == "Maintenance":
        conn.close()
        return False, f"Room {room_num} is currently under Maintenance.", None

    if not guest_name:
        conn.close()
        return False, "Guest name cannot be empty.", None

    try:
        nights = int(nights)
        if nights <= 0:
            nights = 1
    except (ValueError, TypeError):
        nights = 1

    # Check if guest exists or create new guest record
    cursor.execute("SELECT id FROM guests WHERE LOWER(full_name) = LOWER(?)", (guest_name,))
    g_row = cursor.fetchone()
    if g_row:
        guest_id = g_row["id"]
    else:
        cursor.execute("""
        INSERT INTO guests (full_name, phone, email, id_proof_number)
        VALUES (?, ?, ?, ?)
        """, (guest_name, phone or "9999999999", email or "", id_proof_number or ""))
        guest_id = cursor.lastrowid

    # Compute stay dates
    try:
        from datetime import datetime, timedelta
        cin = datetime.now()
        cout = cin + timedelta(days=nights)
        check_in_date = cin.strftime("%Y-%m-%d")
        check_out_date = cout.strftime("%Y-%m-%d")
    except Exception:
        check_in_date = get_current_date_str()
        check_out_date = get_current_date_str()

    booking_code = f"BK-{room_num}-{secrets.token_hex(3).upper()}"
    
    # Check if this room had a confirmed booking for today
    cursor.execute("""
    SELECT id FROM bookings
    WHERE room_id = ? AND guest_id = ? AND status = 'Confirmed'
    """, (room["id"], guest_id))
    existing_bk = cursor.fetchone()

    if existing_bk:
        booking_id = existing_bk["id"]
        cursor.execute("""
        UPDATE bookings SET 
            status = 'Checked-in',
            actual_check_in = CURRENT_TIMESTAMP
        WHERE id = ?
        """, (booking_id,))
    else:
        # Walk-in overlap check
        overlap_query = """
        SELECT id FROM bookings
        WHERE room_id = ? 
          AND status IN ('Confirmed', 'Checked-in')
          AND NOT (check_out_date <= ? OR check_in_date >= ?)
        """
        cursor.execute(overlap_query, (room["id"], check_in_date, check_out_date))
        if cursor.fetchone():
            conn.close()
            return False, f"Room {room_num} is already booked for these dates.", None

        room_price = float(room["price_per_night"])
        subtotal = room_price * nights
        tax_amount = subtotal * (12.0 / 100.0)
        grand_total = subtotal + tax_amount

        cursor.execute("""
        INSERT INTO bookings (booking_code, guest_id, room_id, check_in_date, check_out_date, actual_check_in, room_price, tax_amount, grand_total, status)
        VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?, ?, ?, 'Checked-in')
        """, (booking_code, guest_id, room["id"], check_in_date, check_out_date, room_price, tax_amount, grand_total))
        booking_id = cursor.lastrowid

    # Update Room status to Occupied
    cursor.execute("UPDATE rooms SET status = 'Occupied' WHERE id = ?", (room["id"],))
    conn.commit()
    conn.close()

    total_cost = float(room["price_per_night"]) * nights
    invoice = {
        "booking_id": booking_id,
        "room_num": room_num,
        "type": room["room_type"],
        "guest": guest_name,
        "nights": nights,
        "price_per_night": float(room["price_per_night"]),
        "total_cost": total_cost
    }

    return True, f"Guest {guest_name} successfully checked into Room {room_num}.", invoice


def api_check_out(rooms, query, services_charge=0.0):
    """API non-interactive helper to check out a guest, calculate bill and update room status."""
    query = str(query).strip()
    conn = get_connection()
    cursor = conn.cursor()

    # Find active occupied room or matching guest
    cursor.execute("""
    SELECT r.id as room_id, r.room_number, r.room_type, r.price_per_night, 
           b.id as booking_id, b.check_in_date, b.check_out_date, b.advance_payment, b.discount, b.room_price,
           g.full_name as guest, g.id as guest_id
    FROM rooms r
    JOIN bookings b ON r.id = b.room_id AND b.status = 'Checked-in'
    JOIN guests g ON b.guest_id = g.id
    WHERE r.room_number = ? OR LOWER(g.full_name) LIKE LOWER(?)
    """, (query, f"%{query}%"))
    target = cursor.fetchone()

    if not target:
        conn.close()
        return False, f"No active occupied room found matching '{query}'.", None

    try:
        services_charge = float(services_charge)
        if services_charge < 0:
            services_charge = 0.0
    except (ValueError, TypeError):
        services_charge = 0.0

    # Include any services already attached to the booking in booking_services
    cursor.execute("SELECT COALESCE(SUM(total_price), 0.0) as svc_total FROM booking_services WHERE booking_id = ?", (target["booking_id"],))
    svc_row = cursor.fetchone()
    attached_services = float(svc_row["svc_total"] if isinstance(svc_row, dict) else svc_row[0]) if svc_row and (svc_row["svc_total"] if isinstance(svc_row, dict) else svc_row[0]) else 0.0
    services_charge = services_charge + attached_services

    try:
        from datetime import datetime
        cin = datetime.strptime(target["check_in_date"], "%Y-%m-%d")
        if target.get("check_out_date"):
            cout_sched = datetime.strptime(target["check_out_date"], "%Y-%m-%d")
            sched_nights = (cout_sched - cin).days
        else:
            sched_nights = 1

        cout_actual = datetime.now()
        actual_nights = (cout_actual - cin).days

        nights = max(sched_nights, actual_nights)
        if nights < 1:
            nights = 1
    except Exception:
        nights = 1

    room_price = float(target.get("room_price") or target["price_per_night"])
    if room_price <= 0:
        room_price = float(target["price_per_night"])

    room_charge = room_price * nights
    subtotal = room_charge + services_charge
    tax_rate = 12.0
    tax_amount = subtotal * (tax_rate / 100.0)
    discount = float(target.get("discount", 0.0))
    grand_total = subtotal + tax_amount - discount
    advance_paid = float(target.get("advance_payment", 0.0))
    balance_due = grand_total - advance_paid
    if balance_due < 0:
        balance_due = 0.0

    total_bill = grand_total

    # Record Check-Out in DB
    cursor.execute("""
    UPDATE bookings SET 
        status = 'Checked-out',
        actual_check_out = CURRENT_TIMESTAMP
    WHERE id = ?
    """, (target["booking_id"],))

    # Room transitions to Cleaning status
    cursor.execute("UPDATE rooms SET status = 'Cleaning', housekeeping_status = 'Cleaning' WHERE id = ?", (target["room_id"],))

    # Update Housekeeping Table
    cursor.execute("""
    UPDATE housekeeping SET cleaning_status = 'Cleaning', last_updated = CURRENT_TIMESTAMP
    WHERE room_number = ?
    """, (target["room_number"],))

    # Generate Itemized Invoice Record
    inv_num = f"INV-{target['room_number']}-{secrets.token_hex(3).upper()}"
    cursor.execute("""
    INSERT INTO invoices (invoice_number, booking_id, guest_id, room_id, room_charges, service_charges, discount, tax_rate, tax_amount, grand_total, advance_paid, amount_paid, balance_due, payment_status)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0.0, 'Paid')
    """, (inv_num, target["booking_id"], target["guest_id"], target["room_id"], room_charge, services_charge, discount, tax_rate, tax_amount, grand_total, advance_paid, grand_total))

    # Record Payments
    actual_paid_now = balance_due
    if actual_paid_now > 0:
        cursor.execute("""
        INSERT INTO payments (invoice_number, booking_id, amount, payment_method)
        VALUES (?, ?, ?, 'Cash / Direct')
        """, (inv_num, target["booking_id"], actual_paid_now))
    if advance_paid > 0:
        cursor.execute("""
        INSERT INTO payments (invoice_number, booking_id, amount, payment_method, transaction_ref)
        VALUES (?, ?, ?, 'Advance Payment', 'ADVANCE')
        """, (inv_num, target["booking_id"], advance_paid))

    conn.commit()
    conn.close()

    invoice = {
        "invoice_number": inv_num,
        "room_num": target["room_number"],
        "guest": target["guest"],
        "type": target["room_type"],
        "price_per_night": room_price,
        "nights": nights,
        "room_charge": room_charge,
        "services_charge": services_charge,
        "subtotal": subtotal,
        "tax_rate": tax_rate,
        "tax_amount": tax_amount,
        "discount": discount,
        "advance_paid": advance_paid,
        "grand_total": grand_total,
        "balance_due": balance_due,
        "total_bill": total_bill
    }

    return True, f"Room {target['room_number']} checked out. Marked as Cleaning.", invoice


def api_get_stats(rooms=None):
    """Computes comprehensive dashboard analytics dictionary directly from database."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM rooms")
    total_row = cursor.fetchone()
    total = total_row[0] if total_row else 0

    cursor.execute("SELECT COUNT(*) FROM rooms WHERE status = 'Available'")
    avail_row = cursor.fetchone()
    available = avail_row[0] if avail_row else 0

    cursor.execute("SELECT COUNT(*) FROM rooms WHERE status = 'Occupied'")
    occ_row = cursor.fetchone()
    occupied = occ_row[0] if occ_row else 0

    cursor.execute("SELECT COUNT(*) FROM rooms WHERE status = 'Cleaning'")
    clean_row = cursor.fetchone()
    cleaning = clean_row[0] if clean_row else 0

    cursor.execute("SELECT COUNT(*) FROM rooms WHERE status = 'Maintenance'")
    maint_row = cursor.fetchone()
    maintenance = maint_row[0] if maint_row else 0

    cursor.execute("SELECT COUNT(*) FROM rooms WHERE status = 'Reserved'")
    res_row = cursor.fetchone()
    reserved = res_row[0] if res_row else 0

    cursor.execute("SELECT SUM(grand_total) FROM invoices")
    rev_row = cursor.fetchone()
    revenue = float(rev_row[0]) if rev_row and rev_row[0] is not None else 0.0

    cursor.execute("SELECT SUM(balance_due) FROM invoices WHERE payment_status = 'Pending'")
    pend_row = cursor.fetchone()
    pending_payments = float(pend_row[0]) if pend_row and pend_row[0] is not None else 0.0

    cursor.execute("SELECT COUNT(*) FROM guests")
    gst_row = cursor.fetchone()
    total_guests = gst_row[0] if gst_row else 0

    cursor.execute("SELECT COUNT(*) FROM bookings WHERE status = 'Checked-in'")
    cur_stays_row = cursor.fetchone()
    current_stays = cur_stays_row[0] if cur_stays_row else 0
    
    today_start = datetime.now().strftime("%Y-%m-%d 00:00:00")
    cursor.execute('SELECT COUNT(*) FROM audit_logs WHERE "timestamp" >= ?', (today_start,))
    act_row = cursor.fetchone()
    daily_activity = act_row[0] if act_row else 0

    conn.close()

    occupancy_rate = (occupied / total * 100) if total > 0 else 0

    return {
        "total": total,
        "available": available,
        "occupied": occupied,
        "reserved": reserved,
        "cleaning": cleaning,
        "maintenance": maintenance,
        "total_guests": total_guests,
        "current_stays": current_stays,
        "occupancy_rate": round(occupancy_rate, 1),
        "revenue": round(revenue, 2),
        "pending_payments": round(pending_payments, 2),
        "daily_activity": daily_activity
    }


# ==========================================================================
# CLI TERMINAL HELPERS (PRESERVED FOR main.py)
# ==========================================================================

def print_banner(title):
    """Prints a styled artistic banner header."""
    width = 60
    print("\n" + "═" * width)
    print(f"  ✨ {title.upper()} ✨".center(width))
    print("═" * width)


def display_rooms(rooms=None):
    """Displays an artistic table of all hotel rooms."""
    print_banner("Hotel Room Status")
    rooms = load_rooms()
    
    print(f"  {'ROOM':<8} {'TYPE':<12} {'PRICE/NIGHT':<15} {'STATUS':<15} {'GUEST'}")
    print("  " + "─" * 56)
    
    for room_num, info in rooms.items():
        if info["status"] == "Available":
            status_badge = "🟢 Available"
        elif info["status"] == "Occupied":
            status_badge = "🔴 Occupied"
        elif info["status"] == "Reserved":
            status_badge = "🔵 Reserved"
        elif info["status"] == "Cleaning":
            status_badge = "🟡 Cleaning"
        else:
            status_badge = f"🟠 {info['status']}"
            
        guest_name = info.get("guest") if info.get("guest") else "-"
        print(f"  {room_num:<8} {info['type']:<12} ${info['price']:<14.2f} {status_badge:<15} {guest_name}")
        
    print("  " + "─" * 56)


def check_in_guest(rooms=None):
    """Handles checking a new guest into an available room (CLI mode)."""
    print_banner("Guest Check-In")
    rooms = load_rooms()
    
    available_rooms = [r for r, info in rooms.items() if info["status"] in ["Available", "Clean"]]
    if not available_rooms:
        print("  ⚠️  Sorry! No rooms are currently available for check-in.")
        return

    print(f"  Available Rooms: {', '.join(available_rooms)}")
    room_num = input("  Enter Room Number to book: ").strip()
    guest_name = input("  Enter Guest Name: ").strip()
    nights_str = input("  Enter Number of Nights [1]: ").strip() or "1"

    success, msg, invoice = api_check_in(rooms, room_num, guest_name, nights_str)
    if not success:
        print(f"  ❌ {msg}")
        return

    print("\n" + "┌" + "─" * 44 + "┐")
    print("│         🎉 CHECK-IN CONFIRMED 🎉           │")
    print("├" + "─" * 44 + "┤")
    print(f"│  Guest Name   : {invoice['guest']:<26} │")
    print(f"│  Room Number  : {invoice['room_num']:<26} │")
    print(f"│  Room Type    : {invoice['type']:<26} │")
    print(f"│  Stay Length  : {invoice['nights']:<2} night(s){' ':<15} │")
    print(f"│  Est. Total   : ${invoice['total_cost']:<25.2f} │")
    print("└" + "─" * 44 + "┘")
    print("  💾 Saved to database successfully!")


def check_out_guest(rooms=None):
    """Handles guest check-out and displays bill calculation (CLI mode)."""
    print_banner("Guest Check-Out & Billing")
    rooms = load_rooms()
    
    occupied_rooms = {r: info for r, info in rooms.items() if info["status"] == "Occupied"}
    if not occupied_rooms:
        print("  ℹ️  No rooms are currently occupied.")
        return

    print("  Occupied Rooms:")
    for r, info in occupied_rooms.items():
        print(f"    - Room {r}: {info['guest']}")
    print("  " + "─" * 40)
    
    query = input("\n  Enter Room Number or Guest Name: ").strip()
    add_services = input("  Add Room Service / Mini-Bar charges ($)? [Press Enter for $0]: ").strip()

    success, msg, invoice = api_check_out(rooms, query, add_services)
    if not success:
        print(f"  ❌ {msg}")
        return

    print("\n" + "┌" + "─" * 46 + "┐")
    print("│             🧾 HOTEL INVOICE 🧾              │")
    print("├" + "─" * 46 + "┤")
    print(f"│  Invoice No.   : {invoice['invoice_number']:<27} │")
    print(f"│  Guest Name    : {invoice['guest']:<27} │")
    print(f"│  Room Number   : {invoice['room_num']:<27} │")
    print(f"│  Room Type     : {invoice['type']:<27} │")
    print(f"│  Rate / Night  : ${invoice['price_per_night']:<26.2f} │")
    print(f"│  Nights Stayed : {invoice['nights']:<27} │")
    print("├" + "─" * 46 + "┤")
    print(f"│  Room Total    : ${invoice['room_charge']:<26.2f} │")
    print(f"│  Service Addons: ${invoice['services_charge']:<26.2f} │")
    print("├" + "─" * 46 + "┤")
    print(f"│  FINAL TOTAL   : ${invoice['total_bill']:<26.2f} │")
    print("└" + "─" * 46 + "┘")
    print("  💾 Database updated successfully!")


def display_dashboard(rooms=None):
    """Displays hotel analytics and dashboard summary (CLI mode)."""
    print_banner("Hotel Dashboard")
    stats = api_get_stats()

    print(f"  🏨 Total Rooms      : {stats['total']}")
    print(f"  🟢 Available Rooms  : {stats['available']}")
    print(f"  🔴 Occupied Rooms   : {stats['occupied']}")
    print(f"  🔵 Reserved Rooms   : {stats['reserved']}")
    print(f"  🟡 Cleaning Rooms   : {stats['cleaning']}")
    print(f"  📊 Occupancy Rate   : {stats['occupancy_rate']}%")
    print(f"  💰 Total Revenue    : ${stats['revenue']:.2f}")
    print("  " + "─" * 30)
