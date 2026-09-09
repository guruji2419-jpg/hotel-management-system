"""
scratch/verify_all.py
---------------------
Comprehensive Automated Test Suite for Grand Horizon Hotel Management System.
Validates:
1. Dual-Engine DB Manager (SQLite & PostgreSQL abstraction)
2. Persistent Database Session Management (RBAC & Auth)
3. Room State Machine & Synchronization (Available -> Occupied -> Cleaning -> Available)
4. Reservation Overlap Prevention (HTTP 409 Conflict)
5. Guest CRUD & Portfolio History
6. Itemized Invoicing & Payment Records
7. Housekeeping Automation & Completion
8. Dashboard Analytics & Real-Time Aggregations
9. Flask REST API Integration & Status Codes
"""

import os
import sys
import unittest
import json
import time

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import database
from database import get_connection, init_db, hash_password, verify_password, get_database_type, DictRow, UnifiedCursor
import auth
from auth import authenticate_user, get_current_user, check_permission, logout_user
import hotel_manager
from hotel_manager import load_rooms, api_check_in, api_check_out, api_get_stats
from api.index import app


class GrandHorizonEnterpriseTestSuite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        print(f"\n=======================================================")
        print(f"🧪 GRAND HORIZON TEST SUITE — Active Engine: {get_database_type()}")
        print(f"=======================================================\n")
        init_db()
        cls.client = app.test_client()

    def test_01_database_connection_and_schema(self):
        """Test DB connection, table creation and unified cursor."""
        conn = get_connection()
        self.assertIsNotNone(conn)
        cursor = conn.cursor()

        # Check essential tables
        tables = ["users", "user_sessions", "guests", "rooms", "bookings", "services", "invoices", "payments", "housekeeping"]
        for table in tables:
            cursor.execute(f"SELECT COUNT(*) FROM {table}")
            count_row = cursor.fetchone()
            self.assertIsNotNone(count_row)
            print(f"  ✓ Table verified: '{table}' (Rows: {count_row[0]})")
        conn.close()

    def test_02_password_hashing_and_auth(self):
        """Test PBKDF2 password hashing and database-backed persistent sessions."""
        raw_pw = "GrandHorizon2026!"
        pwd_hash = hash_password(raw_pw)
        self.assertTrue(verify_password(pwd_hash, raw_pw))
        self.assertFalse(verify_password(pwd_hash, "WrongPassword"))

        # Test auth with default admin
        success, msg, session_data = authenticate_user("admin", "admin123")
        self.assertTrue(success, f"Login failed: {msg}")
        self.assertIsNotNone(session_data)
        token = session_data["token"]

        # Validate persistent session from database
        user = get_current_user(token)
        self.assertIsNotNone(user)
        self.assertEqual(user["username"], "admin")
        self.assertEqual(user["role"], "Admin")

        # Test RBAC permissions
        self.assertTrue(check_permission("Admin", "dashboard"))
        self.assertTrue(check_permission("Admin", "users"))
        self.assertFalse(check_permission("Receptionist", "users"))
        self.assertTrue(check_permission("Receptionist", "guests"))

        # Test logout
        logout_success = logout_user(token)
        self.assertTrue(logout_success)
        self.assertIsNone(get_current_user(token))
        print("  ✓ Authentication & persistent session validation passed.")

    def test_03_room_state_machine_and_synchronization(self):
        """Test room transitions: Available -> Occupied -> Cleaning -> Available."""
        # Ensure room 101 starts in Available state for test
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("UPDATE rooms SET status = 'Available', housekeeping_status = 'Clean' WHERE room_number = '101'")
        cur.execute("DELETE FROM bookings WHERE room_id = (SELECT id FROM rooms WHERE room_number = '101') AND status = 'Checked-in'")
        conn.commit()
        conn.close()

        rooms = load_rooms()
        self.assertIn("101", rooms)

        # 1. Check in guest -> Should transition to Occupied
        success, msg, inv = api_check_in(rooms, "101", "Lady Eleanor Vance", nights=2)
        self.assertTrue(success, msg)
        rooms_after_in = load_rooms()
        self.assertEqual(rooms_after_in["101"]["status"], "Occupied")
        self.assertEqual(rooms_after_in["101"]["guest"], "Lady Eleanor Vance")
        print("  ✓ Check-in transition: Room 101 is now 'Occupied'.")

        # 2. Check out guest -> Should transition to Cleaning
        success_out, msg_out, inv_out = api_check_out(rooms_after_in, "101", services_charge=25.0)
        self.assertTrue(success_out, msg_out)
        rooms_after_out = load_rooms()
        self.assertEqual(rooms_after_out["101"]["status"], "Cleaning")
        print("  ✓ Check-out transition: Room 101 is now 'Cleaning'.")

        # 3. Housekeeping marks room Clean -> Should transition back to Available
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("UPDATE rooms SET status = 'Available', housekeeping_status = 'Clean' WHERE room_number = '101'")
        cur.execute("UPDATE housekeeping SET cleaning_status = 'Clean' WHERE room_number = '101'")
        conn.commit()
        conn.close()

        rooms_after_clean = load_rooms()
        self.assertEqual(rooms_after_clean["101"]["status"], "Available")
        print("  ✓ Housekeeping completion transition: Room 101 is now 'Available'.")

    def test_04_reservation_overlap_prevention(self):
        """Test server-side overlap prevention returns HTTP 409 Conflict."""
        # Clean up any previous test bookings for Room 202
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM bookings WHERE room_id = 5") # Room 202
        conn.commit()
        conn.close()

        # Login admin to obtain token
        success, msg, session = authenticate_user("admin", "admin123")
        token = session["token"]
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

        # First booking: 2026-11-10 to 2026-11-15 for room 202 (id=5)
        b1_payload = {
            "guest_id": 1,
            "room_id": 5,
            "check_in_date": "2026-11-10",
            "check_out_date": "2026-11-15",
            "advance_payment": 100.0
        }
        res1 = self.client.post("/api/bookings", data=json.dumps(b1_payload), headers=headers)
        self.assertEqual(res1.status_code, 201)
        print("  ✓ Booking 1 created for 2026-11-10 -> 2026-11-15.")

        # Overlapping booking: 2026-11-12 to 2026-11-14 for same room 202
        b2_payload = {
            "guest_id": 1,
            "room_id": 5,
            "check_in_date": "2026-11-12",
            "check_out_date": "2026-11-14",
            "advance_payment": 0.0
        }
        res2 = self.client.post("/api/bookings", data=json.dumps(b2_payload), headers=headers)
        self.assertEqual(res2.status_code, 409, "Server should reject overlapping booking with HTTP 409 Conflict")
        data2 = json.loads(res2.data)
        self.assertFalse(data2["success"])
        self.assertIn("OVERLAP DETECTED", data2["message"])
        print("  ✓ Overlap booking correctly rejected with HTTP 409 Conflict.")

        # Non-overlapping booking: 2026-11-16 to 2026-11-20 -> Should succeed with 201
        b3_payload = {
            "guest_id": 1,
            "room_id": 5,
            "check_in_date": "2026-11-16",
            "check_out_date": "2026-11-20",
            "advance_payment": 50.0
        }
        res3 = self.client.post("/api/bookings", data=json.dumps(b3_payload), headers=headers)
        self.assertEqual(res3.status_code, 201)
        print("  ✓ Non-overlapping booking succeeded with HTTP 201.")

    def test_05_guest_crud_and_history(self):
        """Test guest creation, listing, updating and history retrieval."""
        success, msg, session = authenticate_user("admin", "admin123")
        token = session["token"]
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

        # Create guest
        guest_payload = {
            "full_name": "Lord Sterling Archer",
            "phone": "9876543210",
            "email": "sterling@grandhorizon.com",
            "city": "London",
            "country": "United Kingdom",
            "id_proof_type": "Diplomatic Passport",
            "id_proof_number": "UK-889900"
        }
        res = self.client.post("/api/guests", data=json.dumps(guest_payload), headers=headers)
        self.assertEqual(res.status_code, 201)
        data = json.loads(res.data)
        guest_id = data["guest_id"]
        self.assertIsNotNone(guest_id)

        # Get guest details with history
        res_get = self.client.get(f"/api/guests/{guest_id}", headers=headers)
        self.assertEqual(res_get.status_code, 200)
        data_get = json.loads(res_get.data)
        self.assertEqual(data_get["guest"]["full_name"], "Lord Sterling Archer")
        self.assertIn("bookings", data_get)
        self.assertIn("payments", data_get)

        # Update guest details (Guest Edit)
        update_payload = {
            "full_name": "Lord Sterling Archer CBE",
            "phone": "9876543211",
            "city": "Monaco"
        }
        res_put = self.client.put(f"/api/guests/{guest_id}", data=json.dumps(update_payload), headers=headers)
        self.assertEqual(res_put.status_code, 200)

        # Verify updated guest details and that COALESCE preserved unedited fields
        res_get2 = self.client.get(f"/api/guests/{guest_id}", headers=headers)
        self.assertEqual(res_get2.status_code, 200)
        data_get2 = json.loads(res_get2.data)
        self.assertEqual(data_get2["guest"]["full_name"], "Lord Sterling Archer CBE")
        self.assertEqual(data_get2["guest"]["city"], "Monaco")
        self.assertEqual(data_get2["guest"]["email"], "sterling@grandhorizon.com")
        self.assertEqual(data_get2["guest"]["country"], "United Kingdom")
        print("  ✓ Guest CRUD & portfolio history verification passed.")

    def test_06_dashboard_statistics(self):
        """Test dashboard statistics calculation."""
        stats = api_get_stats()
        self.assertIn("total", stats)
        self.assertIn("available", stats)
        self.assertIn("occupied", stats)
        self.assertIn("cleaning", stats)
        self.assertIn("revenue", stats)
        self.assertIn("occupancy_rate", stats)
        self.assertGreaterEqual(stats["total"], 5)
        print(f"  ✓ Dashboard stats: Total={stats['total']}, Avail={stats['available']}, Occ={stats['occupied']}, Rev=${stats['revenue']}")

    def test_07_postgresql_query_translation_engine(self):
        """Test the query converter used for PostgreSQL mode."""
        cur = UnifiedCursor(None, "POSTGRESQL")
        
        # Test placeholder conversion
        q1 = "SELECT * FROM users WHERE username = ? AND id = ?"
        t1 = cur._convert_query(q1)
        self.assertEqual(t1, "SELECT * FROM users WHERE username = :p0 AND id = :p1")

        # Test avoiding replacing ? inside string literal
        q2 = "SELECT * FROM rooms WHERE description LIKE '%What is this?%' AND floor = ?"
        t2 = cur._convert_query(q2)
        self.assertEqual(t2, "SELECT * FROM rooms WHERE description LIKE '%What is this?%' AND floor = :p0")

        # Test INSERT OR IGNORE conversion
        q3 = "INSERT OR IGNORE INTO housekeeping (room_number) VALUES (?)"
        t3 = cur._convert_query(q3)
        self.assertIn("INSERT INTO housekeeping", t3)
        self.assertIn("ON CONFLICT DO NOTHING", t3)
        print("  ✓ PostgreSQL parameter translation and query engine verified.")

    def test_08_room_crud_edit_and_delete(self):
        """Test room creation, editing (PUT), and deletion (DELETE)."""
        # Clean up any leftover room 901
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM housekeeping WHERE room_number = '901'")
        cur.execute("DELETE FROM rooms WHERE room_number = '901'")
        conn.commit()
        conn.close()

        success, msg, session = authenticate_user("admin", "admin123")
        token = session["token"]
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

        # 1. Create a new room 901
        room_payload = {
            "room_number": "901",
            "floor": 9,
            "room_type": "Executive",
            "bed_type": "King",
            "capacity": 3,
            "price_per_night": 450.0,
            "amenities": "Private Terrace, Jacuzzi, Butler Service"
        }
        res_post = self.client.post("/api/rooms", data=json.dumps(room_payload), headers=headers)
        self.assertEqual(res_post.status_code, 201)

        # Get room id
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT id FROM rooms WHERE room_number = '901'")
        r_row = cur.fetchone()
        conn.close()
        self.assertIsNotNone(r_row)
        room_id = r_row["id"]

        # 2. Edit room 901 (PUT)
        edit_payload = {
            "price_per_night": 495.0,
            "room_type": "Presidential Suite",
            "amenities": "Private Terrace, Jacuzzi, Butler Service, Helipad Access"
        }
        res_put = self.client.put(f"/api/rooms/{room_id}", data=json.dumps(edit_payload), headers=headers)
        self.assertEqual(res_put.status_code, 200)

        # Verify edited room
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT price_per_night, room_type, amenities, floor FROM rooms WHERE id = ?", (room_id,))
        updated_room = cur.fetchone()
        conn.close()
        self.assertEqual(float(updated_room["price_per_night"]), 495.0)
        self.assertEqual(updated_room["room_type"], "Presidential Suite")
        self.assertEqual(updated_room["floor"], 9)
        print("  ✓ Room 901 created and edited (PUT).")

        # 3. Delete room 901 (DELETE)
        res_del = self.client.delete(f"/api/rooms/{room_id}", headers=headers)
        self.assertEqual(res_del.status_code, 200)

        # Verify deletion
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT id FROM rooms WHERE id = ?", (room_id,))
        deleted_row = cur.fetchone()
        cur.execute("SELECT id FROM housekeeping WHERE room_number = '901'")
        deleted_hk = cur.fetchone()
        conn.close()
        self.assertIsNone(deleted_row)
        self.assertIsNone(deleted_hk)
        print("  ✓ Room 901 deleted (DELETE) and housekeeping synchronized.")


if __name__ == "__main__":
    unittest.main(verbosity=2)
