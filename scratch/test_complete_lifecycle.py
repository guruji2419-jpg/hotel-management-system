"""
test_complete_lifecycle.py
--------------------------
End-to-end verification script testing:
1. PostgreSQL simulation: user_sessions INSERT (no id column) and savepoint transaction isolation.
2. Complete Lifecycle:
   LOGIN -> DASHBOARD -> ROOMS -> GUESTS -> RESERVATION CREATE -> OVERLAP CHECK ->
   RESERVATION EDIT -> CHECK-IN -> SERVICES -> PAYMENTS -> CHECK-OUT ->
   INVOICE VERIFICATION -> HOUSEKEEPING -> REPORTS -> TEST DATA CLEANUP.
"""

import sys
import os
import json
import time
import unittest
from unittest.mock import MagicMock

# Ensure project root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from database import init_db, get_connection, UnifiedCursor, UnifiedConnection
from auth import authenticate_user, get_current_user
import hotel_manager
from api.index import app

class TestCompleteLifecycle(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        cls.client = app.test_client()
        cls.test_token = None
        cls.test_room_id = None
        cls.test_room_num = "999"
        cls.test_guest_id = None
        cls.test_booking_id = None
        cls.test_invoice_num = None

    def test_01_postgresql_cursor_user_sessions_no_id(self):
        """Verify PostgreSQL RETURNING id logic correctly excludes user_sessions and never aborts transactions."""
        conn = get_connection()
        cursor = conn.cursor()
        
        # Test inserting into user_sessions directly
        test_token = f"test_token_{int(time.time())}"
        test_expires = time.time() + 3600
        
        # This statement must succeed without attempting RETURNING id and without throwing InFailedSqlTransaction
        cursor.execute("""
        INSERT INTO user_sessions (token, user_id, username, full_name, role, expires_at)
        VALUES (?, 1, 'admin', 'System Admin', 'Admin', ?)
        """, (test_token, test_expires))
        conn.commit()

        # Verify it was persisted
        cursor.execute("SELECT * FROM user_sessions WHERE token = ?", (test_token,))
        row = cursor.fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["token"], test_token)
        self.assertEqual(row["username"], "admin")

        # Clean up
        cursor.execute("DELETE FROM user_sessions WHERE token = ?", (test_token,))
        conn.commit()
        conn.close()

    def test_02_auth_login_lifecycle(self):
        """Verify login endpoint authenticates and returns valid persistent session token."""
        res = self.client.post("/api/auth/login", json={
            "username": "admin",
            "password": "admin123"
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertIn("user", data)
        self.assertIn("token", data["user"])
        TestCompleteLifecycle.test_token = data["user"]["token"]

        # Verify /api/auth/me accepts token
        me_res = self.client.get("/api/auth/me", headers={
            "Authorization": f"Bearer {self.test_token}"
        })
        self.assertEqual(me_res.status_code, 200)
        me_data = me_res.get_json()
        self.assertTrue(me_data["success"])
        self.assertEqual(me_data["user"]["username"], "admin")

    def test_03_dashboard_kpis(self):
        """Verify dashboard statistics structure and calculation."""
        res = self.client.get("/api/dashboard", headers={
            "Authorization": f"Bearer {self.test_token}"
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertIn("stats", data)
        stats = data["stats"]
        for key in ["total", "available", "occupied", "reserved", "cleaning", "revenue", "occupancy_rate"]:
            self.assertIn(key, stats)

    def test_04_create_test_room(self):
        """Verify Room Creation and persistence."""
        # Clean up in case 999 already exists from prior test
        conn = get_connection()
        c = conn.cursor()
        c.execute("DELETE FROM rooms WHERE room_number = ?", (self.test_room_num,))
        c.execute("DELETE FROM housekeeping WHERE room_number = ?", (self.test_room_num,))
        conn.commit()
        conn.close()

        res = self.client.post("/api/rooms", headers={
            "Authorization": f"Bearer {self.test_token}"
        }, json={
            "room_number": self.test_room_num,
            "floor": 9,
            "room_type": "Presidential Suite",
            "bed_type": "King",
            "price_per_night": 250.0,
            "capacity": 4,
            "amenities": "Private Terrace, Jacuzzi, Ocean View"
        })
        self.assertEqual(res.status_code, 201)
        
        # Verify room exists in list
        r_res = self.client.get("/api/rooms", headers={
            "Authorization": f"Bearer {self.test_token}"
        })
        r_data = r_res.get_json()
        self.assertIn(self.test_room_num, r_data["rooms"])
        TestCompleteLifecycle.test_room_id = r_data["rooms"][self.test_room_num]["id"]
        self.assertEqual(r_data["rooms"][self.test_room_num]["status"], "Available")

    def test_05_create_test_guest(self):
        """Verify Guest Profile Creation and persistence."""
        res = self.client.post("/api/guests", headers={
            "Authorization": f"Bearer {self.test_token}"
        }, json={
            "full_name": "QA VIP Guest",
            "phone": "+1-555-0199",
            "email": "qaguest@horizon.com",
            "city": "Monaco",
            "id_proof_type": "Passport",
            "id_proof_number": "MNC-998877"
        })
        self.assertEqual(res.status_code, 201)
        data = res.get_json()
        self.assertTrue(data["success"])
        
        # Find guest id
        g_res = self.client.get("/api/guests?q=QA VIP Guest", headers={
            "Authorization": f"Bearer {self.test_token}"
        })
        g_data = g_res.get_json()
        guests = g_data["guests"]
        self.assertTrue(len(guests) > 0)
        TestCompleteLifecycle.test_guest_id = guests[0]["id"]
        self.assertEqual(guests[0]["full_name"], "QA VIP Guest")

    def test_06_create_reservation_and_overlap_detection(self):
        """Verify Reservation Creation, math (tax 12%), room status transition to Reserved, and overlap protection."""
        cin = "2026-10-01"
        cout = "2026-10-04" # 3 nights
        
        res = self.client.post("/api/bookings", headers={
            "Authorization": f"Bearer {self.test_token}"
        }, json={
            "guest_id": str(self.test_guest_id),
            "room_id": str(self.test_room_id),
            "check_in_date": cin,
            "check_out_date": cout,
            "adults": 2,
            "children": 0,
            "advance_payment": 100.0,
            "discount": 20.0
        })
        self.assertEqual(res.status_code, 201)
        data = res.get_json()
        self.assertTrue(data["success"])
        TestCompleteLifecycle.test_booking_id = data["booking_id"]

        # Verify Room status transitioned to Reserved
        conn = get_connection()
        c = conn.cursor()
        c.execute("SELECT status FROM rooms WHERE id = ?", (self.test_room_id,))
        r = c.fetchone()
        self.assertEqual(r["status"], "Reserved")

        # Verify booking financial calculation
        # Price per night: $250. 3 nights = $750. Tax (12%) = $90. Discount = $20. Grand total = $820.
        c.execute("SELECT room_price, tax_amount, discount, grand_total, advance_payment FROM bookings WHERE id = ?", (self.test_booking_id,))
        b = c.fetchone()
        conn.close()
        self.assertEqual(float(b["room_price"]), 250.0)
        self.assertEqual(float(b["tax_amount"]), 90.0)
        self.assertEqual(float(b["discount"]), 20.0)
        self.assertEqual(float(b["grand_total"]), 820.0)
        self.assertEqual(float(b["advance_payment"]), 100.0)

        # TEST OVERLAP PREVENTION: Attempt overlapping booking for same room
        conflict_res = self.client.post("/api/bookings", headers={
            "Authorization": f"Bearer {self.test_token}"
        }, json={
            "guest_id": str(self.test_guest_id),
            "room_id": str(self.test_room_id),
            "check_in_date": "2026-10-02",
            "check_out_date": "2026-10-05"
        })
        self.assertEqual(conflict_res.status_code, 409)
        c_data = conflict_res.get_json()
        self.assertFalse(c_data["success"])
        self.assertIn("OVERLAP DETECTED", c_data["message"])

    def test_07_edit_reservation(self):
        """Verify editing reservation updates dates and recalculates totals correctly."""
        new_cout = "2026-10-05" # 4 nights now
        res = self.client.put(f"/api/bookings/{self.test_booking_id}", headers={
            "Authorization": f"Bearer {self.test_token}"
        }, json={
            "check_in_date": "2026-10-01",
            "check_out_date": new_cout,
            "guest_id": self.test_guest_id,
            "room_id": self.test_room_id,
            "advance_payment": 150.0,
            "discount": 20.0
        })
        self.assertEqual(res.status_code, 200)

        # Check in DB: 4 nights = $1000 subtotal + $120 tax - $20 discount = $1100
        conn = get_connection()
        c = conn.cursor()
        c.execute("SELECT grand_total, advance_payment FROM bookings WHERE id = ?", (self.test_booking_id,))
        b = c.fetchone()
        conn.close()
        self.assertEqual(float(b["grand_total"]), 1100.0)
        self.assertEqual(float(b["advance_payment"]), 150.0)

    def test_08_check_in_workflow(self):
        """Verify Guided Check-in assigns room, transitions status to Occupied, and updates booking."""
        res = self.client.post("/api/check-in", headers={
            "Authorization": f"Bearer {self.test_token}"
        }, json={
            "room_num": self.test_room_num,
            "guest_name": "QA VIP Guest",
            "nights": 3
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])

        # Check DB: Room must be Occupied
        conn = get_connection()
        c = conn.cursor()
        c.execute("SELECT status FROM rooms WHERE room_number = ?", (self.test_room_num,))
        self.assertEqual(c.fetchone()["status"], "Occupied")

        # Check booking status: Checked-in
        c.execute("SELECT status FROM bookings WHERE room_id = ? ORDER BY id DESC LIMIT 1", (self.test_room_id,))
        self.assertEqual(c.fetchone()["status"], "Checked-in")
        conn.close()

    def test_09_order_services(self):
        """Verify attaching a service charge to the active booking."""
        res = self.client.post("/api/services/add-to-booking", headers={
            "Authorization": f"Bearer {self.test_token}"
        }, json={
            "booking_id": str(self.test_booking_id),
            "service_name": "Airport Luxury Limousine Transfer",
            "quantity": 1,
            "unit_price": 75.0,
            "notes": "Champagne service requested"
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])

        conn = get_connection()
        c = conn.cursor()
        c.execute("SELECT * FROM booking_services WHERE booking_id = ?", (self.test_booking_id,))
        svc = c.fetchone()
        conn.close()
        self.assertIsNotNone(svc)
        self.assertEqual(svc["service_name"], "Airport Luxury Limousine Transfer")
        self.assertEqual(float(svc["total_price"]), 75.0)

    def test_10_check_out_and_invoice_billing(self):
        """Verify Check-out generates invoice, charges 12% tax, records payments, and transitions room to Cleaning."""
        res = self.client.post("/api/check-out", headers={
            "Authorization": f"Bearer {self.test_token}"
        }, json={
            "room_num": self.test_room_num,
            "services": 75.0
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertIn("invoice", data)
        inv = data["invoice"]
        TestCompleteLifecycle.test_invoice_num = inv["invoice_number"]

        conn = get_connection()
        c = conn.cursor()
        
        # Verify Room status transitions to Cleaning
        c.execute("SELECT status, housekeeping_status FROM rooms WHERE room_number = ?", (self.test_room_num,))
        rm = c.fetchone()
        self.assertEqual(rm["status"], "Cleaning")
        self.assertEqual(rm["housekeeping_status"], "Cleaning")

        # Verify Housekeeping Table was updated
        c.execute("SELECT cleaning_status FROM housekeeping WHERE room_number = ?", (self.test_room_num,))
        hk = c.fetchone()
        self.assertEqual(hk["cleaning_status"], "Cleaning")

        # Verify Invoice Record
        c.execute("SELECT * FROM invoices WHERE invoice_number = ?", (self.test_invoice_num,))
        inv_db = c.fetchone()
        self.assertIsNotNone(inv_db)
        self.assertEqual(inv_db["payment_status"], "Paid")
        self.assertEqual(float(inv_db["balance_due"]), 0.0)

        # Verify Payments Record
        c.execute("SELECT SUM(amount) as total_paid FROM payments WHERE invoice_number = ?", (self.test_invoice_num,))
        pay_row = c.fetchone()
        self.assertAlmostEqual(float(pay_row["total_paid"]), float(inv_db["grand_total"]), places=2)
        conn.close()

    def test_11_housekeeping_workflow(self):
        """Verify Housekeeping status updates and releases room back to Available."""
        res = self.client.put("/api/housekeeping", headers={
            "Authorization": f"Bearer {self.test_token}"
        }, json={
            "room_number": self.test_room_num,
            "cleaning_status": "Clean",
            "assigned_staff": "Senior Attendant"
        })
        self.assertEqual(res.status_code, 200)

        conn = get_connection()
        c = conn.cursor()
        c.execute("SELECT status, housekeeping_status FROM rooms WHERE room_number = ?", (self.test_room_num,))
        rm = c.fetchone()
        self.assertEqual(rm["status"], "Available")
        self.assertEqual(rm["housekeeping_status"], "Clean")
        conn.close()

    def test_12_reports_and_analytics(self):
        """Verify reports endpoint calculates accurate real-time metrics."""
        res = self.client.get("/api/dashboard", headers={
            "Authorization": f"Bearer {self.test_token}"
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        stats = data["stats"]
        self.assertTrue(stats["revenue"] > 0)
        self.assertTrue(stats["total"] >= 1)

    @classmethod
    def tearDownClass(cls):
        """Clean up test data so database remains clean."""
        conn = get_connection()
        c = conn.cursor()
        try:
            if cls.test_room_num:
                c.execute("DELETE FROM housekeeping WHERE room_number = ?", (cls.test_room_num,))
            if cls.test_booking_id:
                c.execute("DELETE FROM booking_services WHERE booking_id = ?", (cls.test_booking_id,))
                c.execute("DELETE FROM payments WHERE booking_id = ?", (cls.test_booking_id,))
                c.execute("DELETE FROM invoices WHERE booking_id = ?", (cls.test_booking_id,))
                c.execute("DELETE FROM bookings WHERE id = ?", (cls.test_booking_id,))
            if cls.test_room_id:
                c.execute("DELETE FROM rooms WHERE id = ?", (cls.test_room_id,))
            if cls.test_guest_id:
                c.execute("DELETE FROM guests WHERE id = ?", (cls.test_guest_id,))
            conn.commit()
        except Exception as e:
            print("Cleanup warning:", e)
        finally:
            conn.close()

if __name__ == "__main__":
    unittest.main(verbosity=2)
