"""
database.py
-----------
SQLite Relational Database Manager for Grand Horizon Hotel System.
Handles schema initialization, data migrations, seeding default records,
and thread-safe database connections (with /tmp fallback for Vercel serverless).
"""

import sqlite3
import os
import hashlib
import binascii
from datetime import datetime

PRIMARY_DB = "hotel.db"
TMP_DB = "/tmp/hotel.db"


def get_db_path():
    """Determines writable SQLite database path."""
    if os.path.exists(PRIMARY_DB):
        return PRIMARY_DB
    if os.path.exists(TMP_DB):
        return TMP_DB
    # Test if current directory is writable
    try:
        with open("test_db_write.tmp", "w") as f:
            f.write("test")
        os.remove("test_db_write.tmp")
        return PRIMARY_DB
    except Exception:
        return TMP_DB


def get_connection():
    """Returns a SQLite connection with dict row factory."""
    db_path = get_db_path()
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def hash_password(password, salt=None):
    """Secure password hashing using PBKDF2 with SHA256."""
    if not salt:
        salt = binascii.hexlify(os.urandom(16)).decode('utf-8')
    pwd_hash = hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        salt.encode('utf-8'),
        100000
    )
    pwd_hash = binascii.hexlify(pwd_hash).decode('utf-8')
    return f"{salt}${pwd_hash}"


def verify_password(stored_password, provided_password):
    """Verifies a provided password against the stored salt$hash string."""
    try:
        salt, pwd_hash = stored_password.split('$')
        computed_hash = hashlib.pbkdf2_hmac(
            'sha256',
            provided_password.encode('utf-8'),
            salt.encode('utf-8'),
            100000
        )
        computed_hash = binascii.hexlify(computed_hash).decode('utf-8')
        return computed_hash == pwd_hash
    except Exception:
        return False


def init_db():
    """Creates database tables and seeds starter data if empty."""
    conn = get_connection()
    cursor = conn.cursor()

    # 1. Users Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        full_name TEXT NOT NULL,
        role TEXT NOT NULL, -- Admin, Manager, Receptionist, Housekeeping
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # 2. Guests Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS guests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        full_name TEXT NOT NULL,
        dob TEXT,
        age INTEGER,
        gender TEXT,
        phone TEXT NOT NULL,
        email TEXT,
        address TEXT,
        city TEXT,
        state TEXT,
        country TEXT DEFAULT 'India',
        nationality TEXT DEFAULT 'Indian',
        id_proof_type TEXT,
        id_proof_number TEXT,
        emergency_name TEXT,
        emergency_phone TEXT,
        adults INTEGER DEFAULT 1,
        children INTEGER DEFAULT 0,
        special_requests TEXT,
        notes TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # 3. Rooms Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS rooms (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        room_number TEXT UNIQUE NOT NULL,
        floor INTEGER DEFAULT 1,
        room_type TEXT NOT NULL, -- Standard, Deluxe, Suite, Executive
        bed_type TEXT DEFAULT 'Double',
        capacity INTEGER DEFAULT 2,
        price_per_night REAL NOT NULL,
        ac_type TEXT DEFAULT 'AC',
        amenities TEXT,
        description TEXT,
        status TEXT DEFAULT 'Available', -- Available, Reserved, Occupied, Cleaning, Maintenance
        housekeeping_status TEXT DEFAULT 'Clean' -- Clean, Dirty, Cleaning, Inspected, Maintenance
    )
    """)

    # 4. Bookings Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS bookings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        booking_code TEXT UNIQUE,
        guest_id INTEGER NOT NULL,
        room_id INTEGER NOT NULL,
        booking_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        check_in_date TEXT NOT NULL,
        check_out_date TEXT NOT NULL,
        actual_check_in TIMESTAMP,
        actual_check_out TIMESTAMP,
        adults INTEGER DEFAULT 1,
        children INTEGER DEFAULT 0,
        booking_source TEXT DEFAULT 'Walk-in',
        status TEXT DEFAULT 'Confirmed', -- Confirmed, Pending, Checked-in, Checked-out, Cancelled, No-show
        special_requests TEXT,
        advance_payment REAL DEFAULT 0.0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (guest_id) REFERENCES guests (id),
        FOREIGN KEY (room_id) REFERENCES rooms (id)
    )
    """)

    # 5. Services Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS services (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        service_name TEXT NOT NULL,
        category TEXT NOT NULL, -- Restaurant, Room Service, Laundry, Extra Bed, Transport, Other
        unit_price REAL NOT NULL
    )
    """)

    # 6. Booking Services Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS booking_services (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        booking_id INTEGER NOT NULL,
        service_id INTEGER,
        service_name TEXT NOT NULL,
        quantity INTEGER DEFAULT 1,
        unit_price REAL NOT NULL,
        total_price REAL NOT NULL,
        date_added TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        notes TEXT,
        FOREIGN KEY (booking_id) REFERENCES bookings (id)
    )
    """)

    # 7. Invoices Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS invoices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        invoice_number TEXT UNIQUE NOT NULL,
        booking_id INTEGER NOT NULL,
        guest_id INTEGER NOT NULL,
        room_id INTEGER NOT NULL,
        issue_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        room_charges REAL DEFAULT 0.0,
        service_charges REAL DEFAULT 0.0,
        discount REAL DEFAULT 0.0,
        tax_rate REAL DEFAULT 12.0,
        tax_amount REAL DEFAULT 0.0,
        grand_total REAL DEFAULT 0.0,
        advance_paid REAL DEFAULT 0.0,
        amount_paid REAL DEFAULT 0.0,
        balance_due REAL DEFAULT 0.0,
        payment_status TEXT DEFAULT 'Pending', -- Paid, Partial, Pending
        FOREIGN KEY (booking_id) REFERENCES bookings (id)
    )
    """)

    # 8. Payments Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        invoice_number TEXT NOT NULL,
        booking_id INTEGER NOT NULL,
        amount REAL NOT NULL,
        payment_method TEXT NOT NULL, -- Cash, UPI, Card, Bank Transfer
        transaction_ref TEXT,
        payment_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # 9. Housekeeping Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS housekeeping (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        room_number TEXT UNIQUE NOT NULL,
        cleaning_status TEXT DEFAULT 'Clean',
        assigned_staff TEXT,
        notes TEXT,
        last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # 10. Audit Logs Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS audit_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        action TEXT NOT NULL,
        details TEXT,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    conn.commit()

    # Seed Default Records if empty
    seed_default_data(conn)
    conn.close()


def seed_default_data(conn):
    """Seeds initial users, rooms, services, and housekeeping records."""
    cursor = conn.cursor()

    # Seed Users
    cursor.execute("SELECT COUNT(*) FROM users")
    if cursor.fetchone()[0] == 0:
        users = [
            ("admin", hash_password("admin123"), "System Admin", "Admin"),
            ("manager", hash_password("manager123"), "Hotel Manager", "Manager"),
            ("reception", hash_password("rec123"), "Front Desk Officer", "Receptionist"),
            ("cleaner", hash_password("clean123"), "Housekeeping Supervisor", "Housekeeping")
        ]
        cursor.executemany(
            "INSERT INTO users (username, password_hash, full_name, role) VALUES (?, ?, ?, ?)",
            users
        )

    # Seed Rooms
    cursor.execute("SELECT COUNT(*) FROM rooms")
    if cursor.fetchone()[0] == 0:
        rooms = [
            ("101", 1, "Standard", "Single", 1, 50.0, "AC", "WiFi, TV", "Cozy standard single room", "Available", "Clean"),
            ("102", 1, "Standard", "Double", 2, 50.0, "AC", "WiFi, TV", "Standard double room", "Available", "Clean"),
            ("103", 1, "Deluxe", "Queen", 2, 80.0, "AC", "WiFi, TV, Mini-bar", "Spacious deluxe queen room", "Available", "Clean"),
            ("201", 2, "Deluxe", "King", 2, 80.0, "AC", "WiFi, TV, Balcony", "Deluxe king with balcony", "Available", "Clean"),
            ("202", 2, "Suite", "King", 4, 150.0, "AC", "WiFi, TV, Jacuzzi, Living Room", "Luxury executive suite", "Available", "Clean")
        ]
        cursor.executemany(
            "INSERT INTO rooms (room_number, floor, room_type, bed_type, capacity, price_per_night, ac_type, amenities, description, status, housekeeping_status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rooms
        )

    # Seed Housekeeping for rooms
    cursor.execute("SELECT room_number FROM rooms")
    room_numbers = [row["room_number"] for row in cursor.fetchall()]
    for rm in room_numbers:
        cursor.execute("INSERT OR IGNORE INTO housekeeping (room_number, cleaning_status, assigned_staff) VALUES (?, 'Clean', 'Housekeeping Staff')", (rm,))

    # Seed Hotel Services Catalog
    cursor.execute("SELECT COUNT(*) FROM services")
    if cursor.fetchone()[0] == 0:
        services = [
            ("Breakfast Buffet", "Restaurant", 15.0),
            ("Dinner Gourmet", "Restaurant", 25.0),
            ("Express Laundry Service", "Laundry", 20.0),
            ("Extra Rollaway Bed", "Extra Bed", 30.0),
            ("Airport Pick & Drop", "Transport", 40.0),
            ("Mini-Bar Beverages", "Room Service", 10.0)
        ]
        cursor.executemany(
            "INSERT INTO services (service_name, category, unit_price) VALUES (?, ?, ?)",
            services
        )

    conn.commit()


# Initialize database on module load
init_db()
