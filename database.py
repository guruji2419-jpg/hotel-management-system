"""
database.py
-----------
Enterprise Dual-Engine Database Manager for Grand Horizon Hotel System.
Supports seamless switching between:
- SQLite (Local development & fallback)
- PostgreSQL (Production on Vercel, Supabase, Neon, AWS RDS, etc.)

Features:
- Automatic detection via DATABASE_URL / POSTGRES_URL environment variables
- SQLAlchemy connection pooling
- Parameter translation ('?' -> ':pX') and dict-like row access for both engines
- DB-backed user_sessions table for stateless multi-instance session synchronization
- Non-destructive idempotent migrations (CREATE TABLE IF NOT EXISTS)
- Safe starter seeding (only if database is empty)
"""

import os
import re
import hashlib
import binascii
from datetime import datetime
from sqlalchemy import create_engine, text

PRIMARY_SQLITE_DB = "hotel.db"
TMP_SQLITE_DB = "/tmp/hotel.db"

def get_database_type():
    """Detects whether PostgreSQL (Production) or SQLite (Local) should be used."""
    db_url = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL") or os.environ.get("POSTGRESQL_URL")
    if db_url and (db_url.startswith("postgres://") or db_url.startswith("postgresql://")):
        return "POSTGRESQL"
    return "SQLITE"

def get_sqlite_path():
    """Determines writable SQLite database path."""
    if os.path.exists(PRIMARY_SQLITE_DB):
        return PRIMARY_SQLITE_DB
    if os.path.exists(TMP_SQLITE_DB):
        return TMP_SQLITE_DB
    # Test if current directory is writable
    try:
        test_file = "test_db_write.tmp"
        with open(test_file, "w") as f:
            f.write("test")
        os.remove(test_file)
        return PRIMARY_SQLITE_DB
    except Exception:
        return TMP_SQLITE_DB

# ==========================================================================
# SQLALCHEMY ENGINE SETUP
# ==========================================================================

_engine = None

def get_engine():
    global _engine
    if _engine is not None:
        return _engine

    db_type = get_database_type()
    if db_type == "POSTGRESQL":
        raw_url = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL") or os.environ.get("POSTGRESQL_URL")
        if raw_url.startswith("postgres://"):
            raw_url = raw_url.replace("postgres://", "postgresql://", 1)
        
        _engine = create_engine(
            raw_url,
            pool_size=5,
            max_overflow=10,
            pool_timeout=30,
            pool_recycle=1800,
            connect_args={'sslmode': 'require'} if 'localhost' not in raw_url and '127.0.0.1' not in raw_url and 'sslmode' not in raw_url else {}
        )
    else:
        from sqlalchemy.pool import NullPool
        db_path = get_sqlite_path()
        _engine = create_engine(
            f"sqlite:///{db_path}",
            poolclass=NullPool,
            connect_args={"check_same_thread": False, "timeout": 30.0}
        )
        from sqlalchemy import event
        @event.listens_for(_engine, "connect")
        def set_sqlite_pragma(dbapi_connection, connection_record):
            try:
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA busy_timeout=30000")
                cursor.execute("PRAGMA synchronous=NORMAL")
                cursor.close()
            except Exception:
                pass
    return _engine

# ==========================================================================
# UNIFIED ROW WRAPPER
# ==========================================================================
class DictRow(dict):
    """Row object allowing key-based ('row[\"name\"]'), .get('name'), and index-based ('row[0]') access."""
    def __init__(self, cols, values):
        super().__init__(zip(cols, values))
        self._values = list(values)

    def __getitem__(self, item):
        if isinstance(item, int):
            return self._values[item]
        return super().__getitem__(item)

    def get(self, k, default=None):
        return super().get(k, default)


# ==========================================================================
# UNIFIED CURSOR & CONNECTION WRAPPERS
# ==========================================================================
class UnifiedCursor:
    """Cursor wrapper that transparently normalizes queries and result sets between SQLite & PostgreSQL."""
    def __init__(self, connection, db_type, parent_conn=None):
        self._conn = connection
        self._db_type = db_type
        self._parent_conn = parent_conn
        self.lastrowid = None
        self.rowcount = -1
        self._results = None

    def _convert_query(self, query):
        """Converts SQLite-style '?' placeholders and SQLite specifics to SQLAlchemy syntax."""
        if "INSERT OR IGNORE INTO" in query.upper() and self._db_type == "POSTGRESQL":
            query = re.sub(r"INSERT\s+OR\s+IGNORE\s+INTO", "INSERT INTO", query, flags=re.IGNORECASE)
            if "ON CONFLICT" not in query.upper():
                query = query.rstrip("; ") + " ON CONFLICT DO NOTHING"

        # Convert '?' to ':p0', ':p1', etc.
        parts = re.split(r"('(?:''|[^'])*')", query)
        new_parts = []
        param_idx = 0
        for i, part in enumerate(parts):
            if i % 2 == 0:
                while "?" in part:
                    part = part.replace("?", f":p{param_idx}", 1)
                    param_idx += 1
            new_parts.append(part)
        
        return "".join(new_parts)

    def execute(self, query, params=None):
        translated = self._convert_query(query)
        params_dict = {}
        if params:
            if isinstance(params, dict):
                params_dict = params
            else:
                params_dict = {f"p{i}": p for i, p in enumerate(params)}
        
        if self._db_type == "POSTGRESQL":
            is_insert = translated.strip().upper().startswith("INSERT")
            has_returning = "RETURNING" in translated.upper()
            
            if is_insert and not has_returning and "ON CONFLICT DO NOTHING" not in translated.upper():
                try_query = translated.rstrip("; ") + " RETURNING id"
                try:
                    self._results = self._conn.execute(text(try_query), params_dict)
                    row = self._results.fetchone()
                    if row:
                        self.lastrowid = getattr(row, "id", None) or row[0]
                    self.rowcount = self._results.rowcount
                    return self
                except Exception:
                    pass
        
        # Ensure transaction is active for modifying statements
        is_modifying = translated.strip().upper().startswith(("INSERT", "UPDATE", "DELETE", "REPLACE", "CREATE", "DROP", "ALTER"))
        if is_modifying and self._parent_conn:
            self._parent_conn._ensure_trans()

        self._results = self._conn.execute(text(translated), params_dict)
        self.lastrowid = self._results.lastrowid if hasattr(self._results, "lastrowid") else None
        self.rowcount = self._results.rowcount
        return self

    def executemany(self, query, seq_of_params):
        translated = self._convert_query(query)
        
        list_of_dicts = []
        for params in seq_of_params:
            if isinstance(params, dict):
                list_of_dicts.append(params)
            else:
                list_of_dicts.append({f"p{i}": p for i, p in enumerate(params)})
        
        self._results = self._conn.execute(text(translated), list_of_dicts)
        self.rowcount = self._results.rowcount
        return self

    def fetchone(self):
        if not self._results:
            return None
        row = self._results.fetchone()
        if row is None:
            return None
        cols = list(self._results.keys())
        return DictRow(cols, row)

    def fetchall(self):
        if not self._results:
            return []
        rows = self._results.fetchall()
        if not rows:
            return []
        cols = list(self._results.keys())
        return [DictRow(cols, r) for r in rows]

    def close(self):
        try:
            if self._results:
                self._results.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


class UnifiedConnection:
    """Connection wrapper that unifies SQLite and PostgreSQL database operations using SQLAlchemy."""
    def __init__(self, sa_conn, db_type):
        self._sa_conn = sa_conn
        self._db_type = db_type
        self._trans = None

    def _ensure_trans(self):
        if self._trans is None and not self._sa_conn.in_transaction():
            try:
                self._trans = self._sa_conn.begin()
            except Exception:
                pass

    def cursor(self):
        return UnifiedCursor(self._sa_conn, self._db_type, self)

    def commit(self):
        if self._trans is not None:
            try:
                self._trans.commit()
            except Exception:
                pass
            self._trans = None
        try:
            if self._sa_conn.in_transaction():
                self._sa_conn.commit()
        except Exception:
            pass

    def rollback(self):
        if self._trans is not None:
            try:
                self._trans.rollback()
            except Exception:
                pass
            self._trans = None
        try:
            if self._sa_conn.in_transaction():
                self._sa_conn.rollback()
        except Exception:
            pass

    def close(self):
        try:
            if self._trans is not None:
                self._trans.rollback()
                self._trans = None
        except Exception:
            pass
        try:
            if self._sa_conn.in_transaction():
                self._sa_conn.rollback()
        except Exception:
            pass
        try:
            self._sa_conn.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            self.rollback()
        else:
            self.commit()
        self.close()


# ==========================================================================
# DATABASE CONNECTION FACTORY
# ==========================================================================
def get_connection():
    """Returns a unified connection object supporting SQLite or PostgreSQL."""
    engine = get_engine()
    conn = engine.connect()
    db_type = get_database_type()
    return UnifiedConnection(conn, db_type)


# ==========================================================================
# SECURE PASSWORD HASHING
# ==========================================================================
def hash_password(password, salt=None):
    """Secure password hashing using PBKDF2 with SHA256 (100,000 rounds)."""
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


# ==========================================================================
# DATABASE SCHEMA INITIALIZATION & MIGRATIONS
# ==========================================================================
def init_db():
    """Idempotently initializes database tables and seeds starter data if empty."""
    db_type = get_database_type()
    conn = get_connection()
    cursor = conn.cursor()

    pk_serial = "SERIAL PRIMARY KEY" if db_type == "POSTGRESQL" else "INTEGER PRIMARY KEY AUTOINCREMENT"
    real_type = "DOUBLE PRECISION" if db_type == "POSTGRESQL" else "REAL"

    # 1. Users Table
    cursor.execute(f"""
    CREATE TABLE IF NOT EXISTS users (
        id {pk_serial},
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        full_name TEXT NOT NULL,
        role TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # 2. Persistent User Sessions Table
    cursor.execute(f"""
    CREATE TABLE IF NOT EXISTS user_sessions (
        token TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL,
        username TEXT NOT NULL,
        full_name TEXT NOT NULL,
        role TEXT NOT NULL,
        expires_at {real_type} NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # 3. Guests Table
    cursor.execute(f"""
    CREATE TABLE IF NOT EXISTS guests (
        id {pk_serial},
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

    # 4. Rooms Table
    cursor.execute(f"""
    CREATE TABLE IF NOT EXISTS rooms (
        id {pk_serial},
        room_number TEXT UNIQUE NOT NULL,
        floor INTEGER DEFAULT 1,
        room_type TEXT NOT NULL,
        bed_type TEXT DEFAULT 'Double',
        capacity INTEGER DEFAULT 2,
        price_per_night {real_type} NOT NULL,
        ac_type TEXT DEFAULT 'AC',
        amenities TEXT,
        description TEXT,
        status TEXT DEFAULT 'Available',
        housekeeping_status TEXT DEFAULT 'Clean'
    )
    """)

    # 5. Bookings Table
    cursor.execute(f"""
    CREATE TABLE IF NOT EXISTS bookings (
        id {pk_serial},
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
        status TEXT DEFAULT 'Confirmed',
        special_requests TEXT,
        advance_payment {real_type} DEFAULT 0.0,
        room_price {real_type} DEFAULT 0.0,
        tax_amount {real_type} DEFAULT 0.0,
        discount {real_type} DEFAULT 0.0,
        grand_total {real_type} DEFAULT 0.0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # Safe migrations for existing databases
    for col, ctype in [("room_price", real_type), ("tax_amount", real_type), ("discount", real_type), ("grand_total", real_type)]:
        try:
            cursor.execute(f"ALTER TABLE bookings ADD COLUMN {col} {ctype} DEFAULT 0.0")
        except Exception:
            pass


    # 6. Services Table
    cursor.execute(f"""
    CREATE TABLE IF NOT EXISTS services (
        id {pk_serial},
        service_name TEXT NOT NULL,
        category TEXT NOT NULL,
        unit_price {real_type} NOT NULL
    )
    """)

    # 7. Booking Services Table
    cursor.execute(f"""
    CREATE TABLE IF NOT EXISTS booking_services (
        id {pk_serial},
        booking_id INTEGER NOT NULL,
        service_id INTEGER,
        service_name TEXT NOT NULL,
        quantity INTEGER DEFAULT 1,
        unit_price {real_type} NOT NULL,
        total_price {real_type} NOT NULL,
        date_added TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        notes TEXT
    )
    """)

    # 8. Invoices Table
    cursor.execute(f"""
    CREATE TABLE IF NOT EXISTS invoices (
        id {pk_serial},
        invoice_number TEXT UNIQUE NOT NULL,
        booking_id INTEGER NOT NULL,
        guest_id INTEGER NOT NULL,
        room_id INTEGER NOT NULL,
        issue_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        room_charges {real_type} DEFAULT 0.0,
        service_charges {real_type} DEFAULT 0.0,
        discount {real_type} DEFAULT 0.0,
        tax_rate {real_type} DEFAULT 12.0,
        tax_amount {real_type} DEFAULT 0.0,
        grand_total {real_type} DEFAULT 0.0,
        advance_paid {real_type} DEFAULT 0.0,
        amount_paid {real_type} DEFAULT 0.0,
        balance_due {real_type} DEFAULT 0.0,
        payment_status TEXT DEFAULT 'Pending'
    )
    """)

    # 9. Payments Table
    cursor.execute(f"""
    CREATE TABLE IF NOT EXISTS payments (
        id {pk_serial},
        invoice_number TEXT NOT NULL,
        booking_id INTEGER NOT NULL,
        amount {real_type} NOT NULL,
        payment_method TEXT NOT NULL,
        transaction_ref TEXT,
        payment_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # 10. Housekeeping Table
    cursor.execute(f"""
    CREATE TABLE IF NOT EXISTS housekeeping (
        id {pk_serial},
        room_number TEXT UNIQUE NOT NULL,
        cleaning_status TEXT DEFAULT 'Clean',
        assigned_staff TEXT,
        notes TEXT,
        last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # 11. Audit Logs Table
    cursor.execute(f"""
    CREATE TABLE IF NOT EXISTS audit_logs (
        id {pk_serial},
        user_id INTEGER,
        action TEXT NOT NULL,
        details TEXT,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    conn.commit()

    # Seed Default Records safely if empty
    seed_default_data(conn)
    conn.close()


def seed_default_data(conn):
    """Seeds initial users, rooms, services, and housekeeping records only if table is empty."""
    cursor = conn.cursor()

    # Seed Users
    cursor.execute("SELECT COUNT(*) FROM users")
    user_count_row = cursor.fetchone()
    user_count = user_count_row[0] if user_count_row else 0

    if user_count == 0:
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
    room_count_row = cursor.fetchone()
    room_count = room_count_row[0] if room_count_row else 0

    if room_count == 0:
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
    room_rows = cursor.fetchall()
    for row in room_rows:
        rm = row["room_number"] if isinstance(row, dict) else row[0]
        cursor.execute("INSERT OR IGNORE INTO housekeeping (room_number, cleaning_status, assigned_staff) VALUES (?, 'Clean', 'Housekeeping Staff')", (rm,))

    # Seed Hotel Services Catalog
    cursor.execute("SELECT COUNT(*) FROM services")
    srv_count_row = cursor.fetchone()
    srv_count = srv_count_row[0] if srv_count_row else 0

    if srv_count == 0:
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


# Initialize database schema safely on module load
try:
    init_db()
except Exception as e:
    print(f"⚠️ [DATABASE] init_db notice: {e}")
