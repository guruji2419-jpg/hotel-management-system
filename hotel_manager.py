"""
hotel_manager.py
----------------
Core logic and data structure for the Hotel Management System.
Bridges SQLite database operations with CLI terminal interface (main.py)
and non-interactive API helpers for Flask backend (api/index.py).
"""

import os
from database import get_connection

# Default initial room data structure fallback
INITIAL_ROOMS = {
    "101": {"type": "Standard", "price": 50,  "status": "Available", "guest": None, "nights": 0, "services": 0},
    "102": {"type": "Standard", "price": 50,  "status": "Available", "guest": None, "nights": 0, "services": 0},
    "103": {"type": "Deluxe",   "price": 80,  "status": "Available", "guest": None, "nights": 0, "services": 0},
    "201": {"type": "Deluxe",   "price": 80,  "status": "Available", "guest": None, "nights": 0, "services": 0},
    "202": {"type": "Suite",    "price": 150, "status": "Available", "guest": None, "nights": 0, "services": 0},
}


def load_rooms():
    """Loads current room states and active guest stays directly from SQLite database."""
    rooms_dict = {}
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        # Query all rooms with active booking details if occupied
        query = """
        SELECT 
            r.room_number, r.room_type, r.price_per_night, r.status,
            g.full_name as guest, b.check_in_date, b.check_out_date
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
                r_num = row["room_number"]
                rooms_dict[r_num] = {
                    "type": row["room_type"],
                    "price": float(row["price_per_night"]),
                    "status": row["status"],
                    "guest": row["guest"] if row["guest"] else None,
                    "nights": 1,
                    "services": 0.0
                }
            return rooms_dict
    except Exception as e:
        print(f"  ⚠️ DB Load warning: {e}. Using fallback rooms.")
        
    return INITIAL_ROOMS.copy()


def save_rooms(rooms):
    """Syncs in-memory room status changes back to SQLite database."""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        for r_num, info in rooms.items():
            cursor.execute("UPDATE rooms SET status = ? WHERE room_number = ?", (info["status"], r_num))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"  ❌ DB Sync error: {e}")


# ==========================================
# NON-INTERACTIVE API HELPER FUNCTIONS
# ==========================================

def api_check_in(rooms, room_num, guest_name, nights):
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

    if room["status"] != "Available":
        conn.close()
        return False, f"Room {room_num} is already {room['status']}.", None

    if not guest_name:
        conn.close()
        return False, "Guest name cannot be empty.", None

    try:
        nights = int(nights)
        if nights <= 0:
            conn.close()
            return False, "Nights must be at least 1.", None
    except (ValueError, TypeError):
        conn.close()
        return False, "Invalid number of nights.", None

    # Check if guest exists or create new guest
    cursor.execute("SELECT id FROM guests WHERE full_name = ?", (guest_name,))
    g_row = cursor.fetchone()
    if g_row:
        guest_id = g_row["id"]
    else:
        cursor.execute("INSERT INTO guests (full_name, phone) VALUES (?, ?)", (guest_name, "9999999999"))
        guest_id = cursor.lastrowid

    # Create Booking Record
    check_in_date = os.popen("date /t").read().strip() if os.name == 'nt' else "2026-09-04"
    booking_code = f"BK-{room_num}-{int(os.urandom(2).hex(), 16)}"
    
    cursor.execute("""
    INSERT INTO bookings (booking_code, guest_id, room_id, check_in_date, check_out_date, status)
    VALUES (?, ?, ?, ?, ?, 'Checked-in')
    """, (booking_code, guest_id, room["id"], check_in_date, check_in_date))
    booking_id = cursor.lastrowid

    # Update Room status to Occupied
    cursor.execute("UPDATE rooms SET status = 'Occupied' WHERE id = ?", (room["id"],))
    conn.commit()
    conn.close()

    total_cost = room["price_per_night"] * nights
    invoice = {
        "booking_id": booking_id,
        "room_num": room_num,
        "type": room["room_type"],
        "guest": guest_name,
        "nights": nights,
        "price_per_night": room["price_per_night"],
        "total_cost": total_cost
    }

    updated_rooms = load_rooms()
    return True, f"Guest {guest_name} successfully checked into Room {room_num}.", invoice


def api_check_out(rooms, query, services_charge=0.0):
    """API non-interactive helper to check out a guest and calculate bill."""
    query = str(query).strip()
    conn = get_connection()
    cursor = conn.cursor()

    # Find room or guest
    cursor.execute("""
    SELECT r.id as room_id, r.room_number, r.room_type, r.price_per_night, b.id as booking_id, g.full_name as guest, g.id as guest_id
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

    nights = 1
    price = float(target["price_per_night"])
    room_charge = price * nights
    total_bill = room_charge + services_charge

    # Record Check-Out in DB
    cursor.execute("UPDATE bookings SET status = 'Checked-out' WHERE id = ?", (target["booking_id"],))
    cursor.execute("UPDATE rooms SET status = 'Cleaning', housekeeping_status = 'Cleaning' WHERE id = ?", (target["room_id"],))

    # Generate Invoice Record
    inv_num = f"INV-{target['room_number']}-{int(os.urandom(2).hex(), 16)}"
    cursor.execute("""
    INSERT INTO invoices (invoice_number, booking_id, guest_id, room_id, room_charges, service_charges, grand_total, amount_paid, payment_status)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'Paid')
    """, (inv_num, target["booking_id"], target["guest_id"], target["room_id"], room_charge, services_charge, total_bill, total_bill))

    conn.commit()
    conn.close()

    invoice = {
        "invoice_number": inv_num,
        "room_num": target["room_number"],
        "guest": target["guest"],
        "type": target["room_type"],
        "price_per_night": price,
        "nights": nights,
        "room_charge": room_charge,
        "services_charge": services_charge,
        "total_bill": total_bill
    }

    updated_rooms = load_rooms()
    return True, f"Room {target['room_number']} checked out. Marked as Cleaning.", invoice


def api_get_stats(rooms):
    """API helper to compute dashboard analytics dictionary."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM rooms")
    total = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM rooms WHERE status = 'Available'")
    available = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM rooms WHERE status = 'Occupied'")
    occupied = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM rooms WHERE status = 'Cleaning'")
    cleaning = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM rooms WHERE status = 'Maintenance'")
    maintenance = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM rooms WHERE status = 'Reserved'")
    reserved = cursor.fetchone()[0]

    cursor.execute("SELECT SUM(grand_total) FROM invoices")
    rev_row = cursor.fetchone()
    revenue = float(rev_row[0]) if rev_row[0] else 0.0

    conn.close()

    occupancy_rate = (occupied / total * 100) if total > 0 else 0

    return {
        "total": total,
        "available": available,
        "occupied": occupied,
        "reserved": reserved,
        "cleaning": cleaning,
        "maintenance": maintenance,
        "occupancy_rate": round(occupancy_rate, 1),
        "revenue": round(revenue, 2)
    }


# ==========================================
# EXISTING CLI FUNCTIONS (PRESERVED FOR main.py)
# ==========================================

def print_banner(title):
    """Prints a styled artistic banner header."""
    width = 60
    print("\n" + "═" * width)
    print(f"  ✨ {title.upper()} ✨".center(width))
    print("═" * width)


def display_rooms(rooms):
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
        else:
            status_badge = f"🟡 {info['status']}"
            
        guest_name = info.get("guest") if info.get("guest") else "-"
        print(f"  {room_num:<8} {info['type']:<12} ${info['price']:<14.2f} {status_badge:<15} {guest_name}")
        
    print("  " + "─" * 56)


def check_in_guest(rooms):
    """Handles checking a new guest into an available room (CLI mode)."""
    print_banner("Guest Check-In")
    rooms = load_rooms()
    
    available_rooms = [r for r, info in rooms.items() if info["status"] == "Available"]
    if not available_rooms:
        print("  ⚠️  Sorry! All rooms are currently occupied.")
        return

    print(f"  Available Rooms: {', '.join(available_rooms)}")
    room_num = input("  Enter Room Number to book: ").strip()
    guest_name = input("  Enter Guest Name: ").strip()
    nights_str = input("  Enter Number of Nights: ").strip()

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
    print("  💾 Saved to SQLite database successfully!")


def check_out_guest(rooms):
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


def display_dashboard(rooms):
    """Displays hotel analytics and dashboard summary (CLI mode)."""
    print_banner("Hotel Dashboard")
    rooms = load_rooms()
    stats = api_get_stats(rooms)

    print(f"  🏨 Total Rooms      : {stats['total']}")
    print(f"  🟢 Available Rooms  : {stats['available']}")
    print(f"  🔴 Occupied Rooms   : {stats['occupied']}")
    print(f"  🟡 Cleaning Rooms   : {stats['cleaning']}")
    print(f"  📊 Occupancy Rate   : {stats['occupancy_rate']}%")
    print(f"  💰 Total Revenue    : ${stats['revenue']:.2f}")
    print("  " + "─" * 30)
