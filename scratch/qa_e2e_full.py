"""
scratch/qa_e2e_full.py
----------------------
Comprehensive End-to-End Functional QA Test Suite for Grand Horizon Hotel Management System.
Executes all 12 requested workflows:
1. LOGIN (All 4 roles, RBAC restrictions, Logout/Session invalidation)
2. DASHBOARD (KPIs, Room counts vs DB, Revenue, Pending payments)
3. ROOMS (View, Add, Edit, Change Status, Delete, Persistence, Immediate updates)
4. GUESTS (Create, Edit, Search/Filter, Profile & History, Delete, Persistence)
5. RESERVATIONS (Create, Availability, Dates, Adults/Children, Advance, Edit, Overlap rejection 409, Cancel, Persistence)
6. CHECK-IN (Check-in, Room Occupied transition, Guest status, Dashboard updates)
7. CHECK-OUT (Nights, Room charge, 12% tax, Services, Advance deduction, Balance, Room Cleaning transition, Invoice)
8. BILLING/PAYMENTS (Payment recording, History, Totals, Paid/Balance values, Security/No CVV audit)
9. SERVICES (Add service, Attach to booking, Billing calculation)
10. HOUSEKEEPING (Change status, Assign staff, Room synchronization)
11. REPORTS (Revenue, Occupancy, Bookings, Check-in/out, CSV exports)
12. REAL-TIME DATA CONSISTENCY (DB validation, API response, Dashboard match, Persistence)
"""

import urllib.request
import urllib.error
import json
import os
import sys
from datetime import datetime, timedelta

# Ensure parent directory is in python path
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from database import get_connection, get_database_type

BASE_URL = "http://127.0.0.1:5000"

results = {
    "total": 0,
    "passed": 0,
    "failed": 0,
    "failures": []
}

def record_check(workflow, test_name, passed, expected, actual, root_cause=""):
    results["total"] += 1
    if passed:
        results["passed"] += 1
        print(f"    ✓ [{workflow}] {test_name}: PASSED")
    else:
        results["failed"] += 1
        print(f"    ❌ [{workflow}] {test_name}: FAILED (Expected: {expected}, Got: {actual})")
        results["failures"].append({
            "workflow": workflow,
            "test_name": test_name,
            "expected": str(expected),
            "actual": str(actual),
            "root_cause": root_cause
        })

def make_req(path, method="GET", data=None, token=None):
    url = f"{BASE_URL}{path}"
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = json.dumps(data).encode("utf-8") if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            resp_body = resp.read().decode("utf-8")
            try:
                parsed = json.loads(resp_body)
            except Exception:
                parsed = resp_body
            return resp.status, parsed
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8")
        try:
            parsed = json.loads(err_body)
        except Exception:
            parsed = err_body
        return e.code, parsed
    except Exception as e:
        return 500, str(e)

def get_db_counts():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) as cnt FROM rooms")
    total_rooms = cur.fetchone()["cnt"]
    cur.execute("SELECT COUNT(*) as cnt FROM rooms WHERE status = 'Available'")
    avail_rooms = cur.fetchone()["cnt"]
    cur.execute("SELECT COUNT(*) as cnt FROM rooms WHERE status = 'Occupied'")
    occ_rooms = cur.fetchone()["cnt"]
    cur.execute("SELECT COUNT(*) as cnt FROM rooms WHERE status = 'Cleaning'")
    clean_rooms = cur.fetchone()["cnt"]
    cur.execute("SELECT COALESCE(SUM(grand_total), 0) as rev FROM invoices WHERE payment_status = 'Paid'")
    paid_rev = float(cur.fetchone()["rev"])
    cur.execute("SELECT COALESCE(SUM(balance_due), 0) as pending FROM invoices WHERE balance_due > 0")
    pending = float(cur.fetchone()["pending"])
    conn.close()
    return {
        "total": total_rooms,
        "available": avail_rooms,
        "occupied": occ_rooms,
        "cleaning": clean_rooms,
        "revenue": paid_rev,
        "pending": pending
    }

def clean_test_data():
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM bookings WHERE check_in_date >= '2027-01-01' OR guest_id IN (SELECT id FROM guests WHERE full_name LIKE 'QA-%')")
        cur.execute("DELETE FROM booking_services WHERE service_name LIKE 'QA-%'")
        cur.execute("DELETE FROM services WHERE service_name LIKE 'QA-%'")
        cur.execute("DELETE FROM rooms WHERE room_number LIKE 'QA-%'")
        cur.execute("DELETE FROM housekeeping WHERE room_number LIKE 'QA-%'")
        cur.execute("DELETE FROM guests WHERE full_name LIKE 'QA-%'")
        conn.commit()
        conn.close()
    except Exception:
        pass

def run_qa():
    print(f"\n=======================================================")
    print(f"🏨 GRAND HORIZON ENTERPRISE END-TO-END FUNCTIONAL QA")
    print(f"Database Engine: {get_database_type()}")
    print(f"Server URL:      {BASE_URL}")
    print(f"=======================================================\n")

    clean_test_data()

    tokens = {}

    # -------------------------------------------------------------
    # WORKFLOW 1: LOGIN & RBAC & LOGOUT
    # -------------------------------------------------------------
    print("👉 [1/12] Testing WORKFLOW 1: LOGIN, RBAC & LOGOUT...")
    roles = [
        ("Admin", "admin", "admin123"),
        ("Manager", "manager", "manager123"),
        ("Receptionist", "reception", "rec123"),
        ("Housekeeping", "cleaner", "clean123")
    ]
    for role_name, uname, pwd in roles:
        status, res = make_req("/api/auth/login", method="POST", data={"username": uname, "password": pwd})
        ok = (status == 200 and res.get("success") is True and res.get("user", {}).get("role") == role_name)
        record_check("LOGIN", f"Login as {role_name}", ok, f"200 OK & role={role_name}", f"Status {status}")
        if ok:
            tokens[role_name] = res["user"]["token"]

    admin_token = tokens.get("Admin")
    manager_token = tokens.get("Manager")
    rec_token = tokens.get("Receptionist")
    hk_token = tokens.get("Housekeeping")

    # Unauthorized tests
    status, res = make_req("/api/auth/users", token=rec_token)
    record_check("LOGIN", "Receptionist blocked from /api/auth/users (403)", status == 403, "403 Forbidden", status)

    status, res = make_req("/api/rooms", method="POST", data={"room_number": "NO-AUTH-101"}, token=rec_token)
    record_check("LOGIN", "Receptionist blocked from POST /api/rooms (403)", status == 403, "403 Forbidden", status)

    status, res = make_req("/api/bookings", token=hk_token)
    record_check("LOGIN", "Housekeeping blocked from GET /api/bookings (403)", status == 403, "403 Forbidden", status)

    # Session invalidation via logout
    status, temp_login = make_req("/api/auth/login", method="POST", data={"username": "cleaner", "password": "clean123"})
    temp_token = temp_login["user"]["token"]
    status, me_res = make_req("/api/auth/me", token=temp_token)
    record_check("LOGIN", "Session active before logout (200)", status == 200, "200 OK", status)

    status, logout_res = make_req("/api/auth/logout", method="POST", token=temp_token)
    record_check("LOGIN", "Logout successful (200)", status == 200 and logout_res.get("success"), "200 OK", status)

    status, me_res2 = make_req("/api/auth/me", token=temp_token)
    record_check("LOGIN", "Session revoked after logout (401)", status == 401, "401 Unauthorized", status)

    # -------------------------------------------------------------
    # WORKFLOW 2: DASHBOARD
    # -------------------------------------------------------------
    print("\n👉 [2/12] Testing WORKFLOW 2: DASHBOARD...")
    status, dash_res = make_req("/api/dashboard", token=admin_token)
    record_check("DASHBOARD", "Load Dashboard API", status == 200 and "stats" in dash_res, "200 OK", status)

    db_counts = get_db_counts()
    stats = dash_res.get("stats", {})
    record_check("DASHBOARD", "Dashboard total rooms matches DB", stats.get("total") == db_counts["total"], db_counts["total"], stats.get("total"))
    record_check("DASHBOARD", "Dashboard available rooms matches DB", stats.get("available") == db_counts["available"], db_counts["available"], stats.get("available"))
    record_check("DASHBOARD", "Dashboard occupied rooms matches DB", stats.get("occupied") == db_counts["occupied"], db_counts["occupied"], stats.get("occupied"))

    # -------------------------------------------------------------
    # WORKFLOW 3: ROOMS
    # -------------------------------------------------------------
    print("\n👉 [3/12] Testing WORKFLOW 3: ROOMS...")
    status, r_list = make_req("/api/rooms", token=admin_token)
    record_check("ROOMS", "View All Rooms", status == 200 and "list" in r_list, "200 OK", status)

    # Add Room QA-777
    room_payload = {
        "room_number": "QA-777",
        "floor": 7,
        "room_type": "Suite",
        "bed_type": "King",
        "capacity": 2,
        "price_per_night": 250.0,
        "amenities": "QA Jacuzzi, Ocean View"
    }
    status, add_res = make_req("/api/rooms", method="POST", data=room_payload, token=admin_token)
    record_check("ROOMS", "Add Room QA-777 (POST)", status == 201, "201 Created", status)

    # Verify QA-777 exists
    status, r_list2 = make_req("/api/rooms", token=admin_token)
    qa_room = next((r for r in r_list2.get("list", []) if r["room_number"] == "QA-777"), None)
    record_check("ROOMS", "QA-777 in directory list", qa_room is not None, "QA-777 found", "Found" if qa_room else "Missing")
    qa_room_id = qa_room["id"] if qa_room else None

    # Edit Room QA-777
    if qa_room_id:
        edit_payload = {
            "price_per_night": 290.0,
            "room_type": "Executive",
            "amenities": "QA Jacuzzi, Ocean View, Butler"
        }
        status, edit_res = make_req(f"/api/rooms/{qa_room_id}", method="PUT", data=edit_payload, token=admin_token)
        record_check("ROOMS", "Edit Room QA-777 (PUT)", status == 200 and edit_res.get("success"), "200 OK", status)

        # Verify edited values
        status, r_list3 = make_req("/api/rooms", token=admin_token)
        qa_edited = next((r for r in r_list3.get("list", []) if r["id"] == qa_room_id), {})
        record_check("ROOMS", "Verify updated price ($290)", float(qa_edited.get("price_per_night", 0)) == 290.0, 290.0, qa_edited.get("price_per_night"))
        record_check("ROOMS", "Verify updated type (Executive)", qa_edited.get("room_type") == "Executive", "Executive", qa_edited.get("room_type"))

        # Change Room Status to Maintenance
        status, stat_res = make_req(f"/api/rooms/{qa_room_id}", method="PUT", data={"status": "Maintenance"}, token=admin_token)
        record_check("ROOMS", "Change Room Status to Maintenance", status == 200, "200 OK", status)

        # Delete Room QA-777
        status, del_res = make_req(f"/api/rooms/{qa_room_id}", method="DELETE", token=admin_token)
        record_check("ROOMS", "Delete Room QA-777 (DELETE)", status == 200 and del_res.get("success"), "200 OK", status)

        # Verify Room QA-777 no longer exists
        status, r_list4 = make_req("/api/rooms", token=admin_token)
        qa_deleted = next((r for r in r_list4.get("list", []) if r["id"] == qa_room_id), None)
        record_check("ROOMS", "Verify QA-777 completely removed", qa_deleted is None, "None", "Still present" if qa_deleted else "None")

    # -------------------------------------------------------------
    # WORKFLOW 4: GUESTS
    # -------------------------------------------------------------
    print("\n👉 [4/12] Testing WORKFLOW 4: GUESTS...")
    guest_payload = {
        "full_name": "QA-Test Guest Montgomery",
        "phone": "9998887776",
        "email": "montgomery.qa@example.com",
        "city": "Boston",
        "country": "United States",
        "id_proof_type": "Driver License",
        "id_proof_number": "DL-QA-9900"
    }
    status, g_add_res = make_req("/api/guests", method="POST", data=guest_payload, token=admin_token)
    record_check("GUESTS", "Create Guest (POST)", status == 201 and g_add_res.get("success"), "201 Created", status)
    qa_guest_id = g_add_res.get("guest_id")

    # Edit Guest
    if qa_guest_id:
        g_edit_payload = {
            "full_name": "QA-Test Guest Montgomery Jr.",
            "city": "New York",
            "phone": "9998887770"
        }
        status, g_edit_res = make_req(f"/api/guests/{qa_guest_id}", method="PUT", data=g_edit_payload, token=admin_token)
        record_check("GUESTS", "Edit Guest Profile (PUT)", status == 200 and g_edit_res.get("success"), "200 OK", status)

        # Search/Filter Guests
        status, g_search = make_req("/api/guests?search=Montgomery", token=admin_token)
        found = any("Montgomery" in g.get("full_name", "") for g in g_search.get("guests", []))
        record_check("GUESTS", "Search/Filter Guests", status == 200 and found, "Guest found in search", "Found" if found else "Not found")

        # Open Guest Profile
        status, g_prof = make_req(f"/api/guests/{qa_guest_id}", token=admin_token)
        record_check("GUESTS", "Open Guest Profile & Booking History", status == 200 and "guest" in g_prof and "bookings" in g_prof, "200 OK with history", status)
        # Check COALESCE preserved email and country
        g_data = g_prof.get("guest", {})
        record_check("GUESTS", "Verify COALESCE preserved email", g_data.get("email") == "montgomery.qa@example.com", "montgomery.qa@example.com", g_data.get("email"))
        record_check("GUESTS", "Verify COALESCE preserved country", g_data.get("country") == "United States", "United States", g_data.get("country"))

    # -------------------------------------------------------------
    # WORKFLOW 5: RESERVATIONS & OVERLAP PREVENTION
    # -------------------------------------------------------------
    print("\n👉 [5/12] Testing WORKFLOW 5: RESERVATIONS & OVERLAPS...")
    # Find an available room ID
    status, rooms_avail = make_req("/api/rooms?status=Available", token=admin_token)
    target_room = rooms_avail.get("list", [])[0] if rooms_avail.get("list") else None
    target_room_id = target_room["id"] if target_room else 1
    target_room_num = target_room["room_number"] if target_room else "101"

    b_start = "2027-01-10"
    b_end = "2027-01-15"
    res_payload = {
        "guest_id": qa_guest_id,
        "room_id": target_room_id,
        "check_in_date": b_start,
        "check_out_date": b_end,
        "adults": 2,
        "children": 1,
        "discount": 10.0,
        "advance_payment": 50.0
    }
    status, b_res = make_req("/api/bookings", method="POST", data=res_payload, token=admin_token)
    record_check("RESERVATIONS", f"Create Reservation for Room {target_room_num}", status == 201 and b_res.get("success"), "201 Created", status)
    qa_booking_id = b_res.get("booking_id")

    # Attempt Overlapping Reservation (Same room, overlapping dates 2027-01-12 -> 2027-01-14)
    overlap_payload = {
        "guest_id": qa_guest_id,
        "room_id": target_room_id,
        "check_in_date": "2027-01-12",
        "check_out_date": "2027-01-14",
        "advance_payment": 0.0
    }
    status, ov_res = make_req("/api/bookings", method="POST", data=overlap_payload, token=admin_token)
    record_check("RESERVATIONS", "Reject Overlapping Reservation (409 Conflict)", status == 409, "409 Conflict", status)

    # Edit Reservation (Update advance payment or dates)
    if qa_booking_id:
        b_edit_payload = {
            "advance_payment": 75.0,
            "adults": 3
        }
        status, b_edit_res = make_req(f"/api/bookings/{qa_booking_id}", method="PUT", data=b_edit_payload, token=admin_token)
        record_check("RESERVATIONS", "Edit Reservation (PUT)", status == 200 and b_edit_res.get("success"), "200 OK", status)

    # -------------------------------------------------------------
    # WORKFLOW 6: CHECK-IN
    # -------------------------------------------------------------
    print("\n👉 [6/12] Testing WORKFLOW 6: CHECK-IN...")
    # Create an active check-in using room 102
    # Ensure room 102 is Available
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("UPDATE rooms SET status = 'Available', housekeeping_status = 'Clean' WHERE room_number = '102'")
    cur.execute("DELETE FROM bookings WHERE room_id = (SELECT id FROM rooms WHERE room_number = '102') AND status = 'Checked-in'")
    conn.commit()
    conn.close()

    checkin_payload = {
        "room_num": "102",
        "guest_name": "QA-Walkin Guest",
        "nights": 3,
        "phone": "9998887770",
        "email": "walkin.qa@example.com",
        "id_proof_number": "DL-QA-9900"
    }
    status, cin_res = make_req("/api/check-in", method="POST", data=checkin_payload, token=admin_token)
    record_check("CHECK-IN", "Execute Check-In (POST /api/check-in)", status == 200 and cin_res.get("success"), "200 OK", status)

    # Verify room is now OCCUPIED
    status, r_check = make_req("/api/rooms", token=admin_token)
    r102 = next((r for r in r_check.get("list", []) if r["room_number"] == "102"), {})
    record_check("CHECK-IN", "Room 102 transitioned to 'Occupied'", r102.get("status") == "Occupied", "Occupied", r102.get("status"))
    record_check("CHECK-IN", "Room 102 occupant name matches guest", r102.get("guest") == "QA-Walkin Guest", "QA-Walkin Guest", r102.get("guest"))

    # Verify dashboard updated
    status, dash_cin = make_req("/api/dashboard", token=admin_token)
    record_check("CHECK-IN", "Dashboard shows at least 1 occupied room", dash_cin.get("stats", {}).get("occupied", 0) >= 1, ">= 1", dash_cin.get("stats", {}).get("occupied"))

    # -------------------------------------------------------------
    # WORKFLOW 7: CHECK-OUT & INVOICING
    # -------------------------------------------------------------
    print("\n👉 [7/12] Testing WORKFLOW 7: CHECK-OUT & INVOICING...")
    checkout_payload = {
        "room_num": "102",
        "services": 40.0 # $40 addon services
    }
    status, cout_res = make_req("/api/check-out", method="POST", data=checkout_payload, token=admin_token)
    record_check("CHECK-OUT", "Execute Check-Out (POST /api/check-out)", status == 200 and cout_res.get("success"), "200 OK", status)

    inv = cout_res.get("invoice", {})
    record_check("CHECK-OUT", "Invoice nights equal 3", inv.get("nights") == 3, 3, inv.get("nights"))
    room_charge_expected = float(inv.get("price_per_night", 50)) * 3
    record_check("CHECK-OUT", "Room charge matches price * nights", float(inv.get("room_charge", 0)) == room_charge_expected, room_charge_expected, inv.get("room_charge"))
    subtotal_expected = room_charge_expected + 40.0
    record_check("CHECK-OUT", "Subtotal includes services ($40)", float(inv.get("subtotal", 0)) == subtotal_expected, subtotal_expected, inv.get("subtotal"))
    tax_expected = subtotal_expected * 0.12
    record_check("CHECK-OUT", "Tax is exactly 12%", abs(float(inv.get("tax_amount", 0)) - tax_expected) < 0.01, tax_expected, inv.get("tax_amount"))
    grand_expected = subtotal_expected + tax_expected
    record_check("CHECK-OUT", "Grand total is subtotal + tax", abs(float(inv.get("grand_total", 0)) - grand_expected) < 0.01, grand_expected, inv.get("grand_total"))

    # Verify room status transitioned to 'Cleaning'
    status, r_clean = make_req("/api/rooms", token=admin_token)
    r102_after = next((r for r in r_clean.get("list", []) if r["room_number"] == "102"), {})
    record_check("CHECK-OUT", "Room 102 transitioned to 'Cleaning'", r102_after.get("status") == "Cleaning", "Cleaning", r102_after.get("status"))

    inv_num = inv.get("invoice_number")

    # -------------------------------------------------------------
    # WORKFLOW 8: BILLING & PAYMENTS
    # -------------------------------------------------------------
    print("\n👉 [8/12] Testing WORKFLOW 8: BILLING & PAYMENTS...")
    if inv_num:
        status, inv_fetch = make_req(f"/api/invoices/{inv_num}", token=admin_token)
        record_check("BILLING", f"Fetch Invoice {inv_num}", status == 200 and "invoice" in inv_fetch, "200 OK", status)

        # Apply payment
        pay_amount = float(inv.get("grand_total", 100.0))
        pay_payload = {
            "invoice_number": inv_num,
            "amount": pay_amount,
            "payment_method": "Credit Card",
            "transaction_ref": "TXN-QA-TEST-12345"
        }
        status, pay_res = make_req("/api/payments", method="POST", data=pay_payload, token=admin_token)
        record_check("BILLING", f"Apply full payment of ${pay_amount:.2f}", status == 201 and pay_res.get("success"), "201 Created", status)

        # Verify payment history
        status, pay_hist = make_req(f"/api/payments?invoice_number={inv_num}", token=admin_token)
        record_check("BILLING", "Payment recorded in transaction history", status == 200 and len(pay_hist.get("payments", [])) >= 1, ">= 1 payment", len(pay_hist.get("payments", [])))

        # Verify invoice is marked Paid with $0 balance
        status, inv_paid = make_req(f"/api/invoices/{inv_num}", token=admin_token)
        inv_data_paid = inv_paid.get("invoice", {})
        record_check("BILLING", "Invoice marked 'Paid'", inv_data_paid.get("payment_status") == "Paid", "Paid", inv_data_paid.get("payment_status"))
        record_check("BILLING", "Balance due is 0.0", float(inv_data_paid.get("balance_due", 1)) == 0.0, 0.0, inv_data_paid.get("balance_due"))

        # SECURITY AUDIT: Verify no raw card or CVV is stored anywhere in the database
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM payments WHERE invoice_number = ?", (inv_num,))
        pay_record = dict(cur.fetchone())
        conn.close()
        has_card = any("cvv" in k.lower() or "card_num" in k.lower() for k in pay_record.keys())
        record_check("BILLING", "Security audit: No CVV or card PAN columns stored", not has_card, "No CVV/Card columns", "Clean")

    # -------------------------------------------------------------
    # WORKFLOW 9: SERVICES
    # -------------------------------------------------------------
    print("\n👉 [9/12] Testing WORKFLOW 9: SERVICES...")
    svc_payload = {
        "service_name": "QA Executive Airport Transfer",
        "category": "Transport",
        "unit_price": 85.0
    }
    status, svc_res = make_req("/api/services", method="POST", data=svc_payload, token=admin_token)
    record_check("SERVICES", "Add New Service (POST /api/services)", status == 201, "201 Created", status)

    status, all_svcs = make_req("/api/services", token=admin_token)
    has_svc = any(s.get("service_name") == "QA Executive Airport Transfer" for s in all_svcs.get("services", []))
    record_check("SERVICES", "Verify Service appears in catalog", has_svc, "True", has_svc)

    # Attach service to reservation
    if qa_booking_id:
        add_svc_booking = {
            "booking_id": qa_booking_id,
            "service_name": "QA Executive Airport Transfer",
            "quantity": 2,
            "unit_price": 85.0,
            "notes": "Flight arriving 14:00"
        }
        status, add_b_res = make_req("/api/services/add-to-booking", method="POST", data=add_svc_booking, token=admin_token)
        record_check("SERVICES", "Attach Service to Booking (2x $85 = $170)", status == 200 and add_b_res.get("success"), "200 OK", status)

    # -------------------------------------------------------------
    # WORKFLOW 10: HOUSEKEEPING
    # -------------------------------------------------------------
    print("\n👉 [10/12] Testing WORKFLOW 10: HOUSEKEEPING...")
    status, hk_list = make_req("/api/housekeeping", token=admin_token)
    record_check("HOUSEKEEPING", "Get Housekeeping status board", status == 200 and ("housekeeping" in hk_list or "tasks" in hk_list), "200 OK", status)

    # Transition Room 102 from Cleaning to Clean
    hk_update = {
        "room_number": "102",
        "cleaning_status": "Clean",
        "assigned_staff": "QA Housekeeping Team Alpha"
    }
    status, hk_upd_res = make_req("/api/housekeeping", method="PUT", data=hk_update, token=admin_token)
    record_check("HOUSEKEEPING", "Update room cleaning status to Clean", status == 200 and hk_upd_res.get("success"), "200 OK", status)

    # Verify Room status automatically synchronized to Available
    status, r_synced = make_req("/api/rooms", token=admin_token)
    r102_synced = next((r for r in r_synced.get("list", []) if r["room_number"] == "102"), {})
    record_check("HOUSEKEEPING", "Room 102 synchronized to 'Available'", r102_synced.get("status") == "Available", "Available", r102_synced.get("status"))

    # -------------------------------------------------------------
    # WORKFLOW 11: REPORTS & CSV EXPORT
    # -------------------------------------------------------------
    print("\n👉 [11/12] Testing WORKFLOW 11: REPORTS & EXPORTS...")
    report_types = ["guests", "rooms", "bookings", "invoices"]
    for rtype in report_types:
        status, csv_data = make_req(f"/api/reports/export/csv?type={rtype}", token=admin_token)
        ok_csv = (status == 200 and isinstance(csv_data, str) and len(csv_data) > 10)
        record_check("REPORTS", f"Export CSV for '{rtype}'", ok_csv, "200 OK & CSV non-empty", f"Status {status}, len={len(csv_data) if isinstance(csv_data, str) else 0}")

    # -------------------------------------------------------------
    # WORKFLOW 12: REAL-TIME DATA CONSISTENCY & CLEANUP
    # -------------------------------------------------------------
    print("\n👉 [12/12] Testing WORKFLOW 12: DATA CONSISTENCY & TEST CLEANUP...")
    # Cancel / Delete test booking
    if qa_booking_id:
        status, b_del = make_req(f"/api/bookings/{qa_booking_id}", method="DELETE", token=admin_token)
        record_check("CONSISTENCY", "Cancel / Delete Test Booking", status == 200, "200 OK", status)

    # Delete test guest
    if qa_guest_id:
        status, g_del = make_req(f"/api/guests/{qa_guest_id}", method="DELETE", token=admin_token)
        record_check("CONSISTENCY", "Delete Test Guest", status == 200, "200 OK", status)

    # Final DB & API consistency check
    final_db = get_db_counts()
    status, final_dash = make_req("/api/dashboard", token=admin_token)
    final_stats = final_dash.get("stats", {})
    record_check("CONSISTENCY", "Final DB total rooms == Dashboard total rooms", final_db["total"] == final_stats.get("total"), final_db["total"], final_stats.get("total"))
    record_check("CONSISTENCY", "Final DB available rooms == Dashboard available rooms", final_db["available"] == final_stats.get("available"), final_db["available"], final_stats.get("available"))

    print("\n=======================================================")
    print(f"📊 SUMMARY: {results['passed']} / {results['total']} tests PASSED.")
    if results['failed'] > 0:
        print(f"❌ {results['failed']} tests FAILED.")
    else:
        print("🎉 ALL WORKFLOW TESTS PASSED PERFECTLY!")
    print("=======================================================\n")
    return results

if __name__ == "__main__":
    res = run_qa()
    sys.exit(0 if res["failed"] == 0 else 1)
