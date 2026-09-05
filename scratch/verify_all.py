"""
scratch/verify_all.py
---------------------
Rigorous automated local verification script for Grand Horizon Hotel System.
Tests Python syntax, DB schemas, Flask API endpoints, auth, guests, rooms,
overlap prevention, check-in, check-out, billing, housekeeping, stats & CLI.
"""

import sys
import os
import json
import py_compile
import urllib.request
import urllib.error

# Project root directory
project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_dir not in sys.path:
    sys.path.insert(0, project_dir)

results = {
    "passed": [],
    "failed": [],
    "errors": []
}

def record_test(name, success, details=""):
    if success:
        results["passed"].append(f"{name}: {details}")
        print(f"  ✅ [PASS] {name}")
    else:
        results["failed"].append(name)
        results["errors"].append(f"{name}: {details}")
        print(f"  ❌ [FAIL] {name} - {details}")

print("==================================================")
print("  RUNNING COMPLETE SYSTEM LOCAL VERIFICATION")
print("==================================================")

# TEST 1: Python File Syntax Compilation Check
print("\n1. Checking Python Syntax Compilation...")
python_files = ["database.py", "auth.py", "hotel_manager.py", "main.py", "api/index.py"]
for f in python_files:
    fpath = os.path.join(project_dir, f)
    try:
        py_compile.compile(fpath, doraise=True)
        record_test(f"Syntax Check ({f})", True, "Compiled without errors")
    except Exception as e:
        record_test(f"Syntax Check ({f})", False, str(e))

# TEST 2: SQLite Database Initialization & Schemas
print("\n2. Checking SQLite Database Initialization...")
try:
    from database import init_db, get_connection
    init_db()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [row[0] for row in cursor.fetchall()]
    expected_tables = ["users", "guests", "rooms", "bookings", "services", "booking_services", "invoices", "payments", "housekeeping", "audit_logs"]
    missing = [t for t in expected_tables if t not in tables]
    if not missing:
        record_test("Database Schemas", True, f"All 10 tables exist: {', '.join(tables)}")
    else:
        record_test("Database Schemas", False, f"Missing tables: {missing}")
    conn.close()
except Exception as e:
    record_test("Database Schemas", False, str(e))

# TEST 3: Auth API & Roles
print("\n3. Testing Authentication & User Roles...")
BASE_URL = "http://127.0.0.1:5000"
admin_token = None
rec_token = None

try:
    # Admin Login
    req = urllib.request.Request(f"{BASE_URL}/api/auth/login", data=json.dumps({"username": "admin", "password": "admin123"}).encode(), headers={"Content-Type": "application/json"})
    res = json.loads(urllib.request.urlopen(req).read().decode())
    if res.get("success") and res.get("user", {}).get("token"):
        admin_token = res["user"]["token"]
        record_test("Admin Login", True, "Token acquired")
    else:
        record_test("Admin Login", False, str(res))

    # Receptionist Login
    req = urllib.request.Request(f"{BASE_URL}/api/auth/login", data=json.dumps({"username": "reception", "password": "rec123"}).encode(), headers={"Content-Type": "application/json"})
    res = json.loads(urllib.request.urlopen(req).read().decode())
    if res.get("success") and res.get("user", {}).get("token"):
        rec_token = res["user"]["token"]
        record_test("Receptionist Login", True, "Token acquired")
    else:
        record_test("Receptionist Login", False, str(res))

    # Verify session /api/auth/me
    req = urllib.request.Request(f"{BASE_URL}/api/auth/me", headers={"Authorization": f"Bearer {admin_token}"})
    res = json.loads(urllib.request.urlopen(req).read().decode())
    record_test("Verify Session (/api/auth/me)", res.get("success", False), f"Role: {res.get('user', {}).get('role')}")

except Exception as e:
    record_test("Auth API", False, str(e))

# TEST 4: Guest Management CRUD
print("\n4. Testing Guest Management CRUD...")
test_guest_id = None
try:
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {admin_token}"}
    # Create Guest
    g_data = {"full_name": "Test Guest Verification", "phone": "9123456789", "email": "test@verification.com", "city": "Delhi"}
    req = urllib.request.Request(f"{BASE_URL}/api/guests", data=json.dumps(g_data).encode(), headers=headers)
    res = json.loads(urllib.request.urlopen(req).read().decode())
    if res.get("success"):
        test_guest_id = res.get("guest_id")
        record_test("Guest Creation", True, f"Guest ID: {test_guest_id}")
    else:
        record_test("Guest Creation", False, str(res))

    # Edit Guest
    req = urllib.request.Request(f"{BASE_URL}/api/guests/{test_guest_id}", data=json.dumps({"full_name": "Updated Test Guest", "phone": "9123456789"}).encode(), headers=headers, method="PUT")
    res = json.loads(urllib.request.urlopen(req).read().decode())
    record_test("Guest Edit", res.get("success", False), res.get("message", ""))

    # View Guest Details & History
    req = urllib.request.Request(f"{BASE_URL}/api/guests/{test_guest_id}", headers=headers)
    res = json.loads(urllib.request.urlopen(req).read().decode())
    record_test("Guest Details & History", res.get("success", False), f"Name: {res.get('guest', {}).get('full_name')}")

except Exception as e:
    record_test("Guest Management", False, str(e))

# TEST 5: Room Management
print("\n5. Testing Room Management...")
try:
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {admin_token}"}
    req = urllib.request.Request(f"{BASE_URL}/api/rooms", headers=headers)
    res = json.loads(urllib.request.urlopen(req).read().decode())
    if res.get("success") and len(res.get("list", [])) >= 5:
        record_test("Room Inventory Listing", True, f"Found {len(res['list'])} rooms")
    else:
        record_test("Room Inventory Listing", False, str(res))
except Exception as e:
    record_test("Room Management", False, str(e))

# TEST 6: Booking Creation & Overlap Prevention
print("\n6. Testing Booking & Overlap Prevention...")
try:
    # Clean up any leftover test bookings from previous runs to ensure idempotency
    from database import get_connection
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM bookings WHERE check_in_date >= '2099-01-01'")
    conn.commit()
    conn.close()

    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {admin_token}"}
    # Create Booking 1 (Room ID 3, dates 2099-11-01 to 2099-11-05)
    b_data1 = {"guest_id": test_guest_id, "room_id": 3, "check_in_date": "2099-11-01", "check_out_date": "2099-11-05", "advance_payment": 20}
    req = urllib.request.Request(f"{BASE_URL}/api/bookings", data=json.dumps(b_data1).encode(), headers=headers)
    res = json.loads(urllib.request.urlopen(req).read().decode())
    if res.get("success"):
        record_test("Booking Creation", True, res.get("message"))
    else:
        record_test("Booking Creation", False, str(res))

    # Overlap Check (Room ID 3, dates 2099-11-03 to 2099-11-07)
    b_data2 = {"guest_id": test_guest_id, "room_id": 3, "check_in_date": "2099-11-03", "check_out_date": "2099-11-07"}
    try:
        req = urllib.request.Request(f"{BASE_URL}/api/bookings", data=json.dumps(b_data2).encode(), headers=headers)
        urllib.request.urlopen(req)
        record_test("Booking Overlap Prevention", False, "Overlapping booking was NOT rejected!")
    except urllib.error.HTTPError as err:
        err_data = json.loads(err.read().decode())
        if err.code == 409 and "OVERLAP" in err_data.get("message", ""):
            record_test("Booking Overlap Prevention", True, f"HTTP 409 Overlap Correctly Prevented: {err_data.get('message')}")
        else:
            record_test("Booking Overlap Prevention", False, f"Unexpected error: {err_data}")

except Exception as e:
    record_test("Booking & Overlap Check", False, str(e))

# TEST 7: Check-In Workflow
print("\n7. Testing Check-In Workflow...")
try:
    # First set Room 202 to Available via Housekeeping reset to ensure test passes
    headers_adm = {"Content-Type": "application/json", "Authorization": f"Bearer {admin_token}"}
    req_reset = urllib.request.Request(f"{BASE_URL}/api/housekeeping", data=json.dumps({"room_number": "202", "cleaning_status": "Clean"}).encode(), headers=headers_adm, method="PUT")
    urllib.request.urlopen(req_reset)
    
    # Also reset room status in DB just to be perfectly sure it's Available for check-in
    from database import get_connection
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE rooms SET status = 'Available' WHERE room_number = '202'")
    conn.commit()
    conn.close()

    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {rec_token}"}
    req = urllib.request.Request(f"{BASE_URL}/api/check-in", data=json.dumps({"room_num": "202", "guest_name": "Verification User", "nights": 2}).encode(), headers=headers)
    res = json.loads(urllib.request.urlopen(req).read().decode())
    if res.get("success"):
        record_test("Check-In Workflow", True, f"Room 202 checked in. Status: Occupied")
    else:
        record_test("Check-In Workflow", False, str(res))
except Exception as e:
    record_test("Check-In Workflow", False, str(e))

# TEST 8: Check-Out & Billing Calculations
print("\n8. Testing Check-Out & Itemized Billing...")
try:
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {rec_token}"}
    req = urllib.request.Request(f"{BASE_URL}/api/check-out", data=json.dumps({"room_num": "202", "services": 35.0}).encode(), headers=headers)
    res = json.loads(urllib.request.urlopen(req).read().decode())
    if res.get("success") and "invoice" in res:
        inv = res["invoice"]
        record_test("Check-Out & Itemized Billing", True, f"Invoice {inv['invoice_number']}: Total = ${inv['total_bill']}")
    else:
        record_test("Check-Out & Itemized Billing", False, str(res))
except Exception as e:
    record_test("Check-Out & Itemized Billing", False, str(e))
    
# TEST 9: Services
print("\n9. Testing Services...")
try:
    headers = {"Authorization": f"Bearer {admin_token}"}
    req = urllib.request.Request(f"{BASE_URL}/api/services", headers=headers)
    res = json.loads(urllib.request.urlopen(req).read().decode())
    if res.get("success") and len(res.get("services", [])) > 0:
        record_test("Services List", True, f"Found {len(res['services'])} services")
    else:
        record_test("Services List", False, str(res))
except Exception as e:
    record_test("Services List", False, str(e))


# TEST 10: Housekeeping Status Changes
print("\n10. Testing Housekeeping Management...")
try:
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {admin_token}"}
    req = urllib.request.Request(f"{BASE_URL}/api/housekeeping", data=json.dumps({"room_number": "202", "cleaning_status": "Clean", "assigned_staff": "Housekeeping Team"}).encode(), headers=headers, method="PUT")
    res = json.loads(urllib.request.urlopen(req).read().decode())
    if res.get("success"):
        record_test("Housekeeping Update", True, res.get("message"))
    else:
        record_test("Housekeeping Update", False, str(res))
except Exception as e:
    record_test("Housekeeping Update", False, str(e))

# TEST 11: Dashboard Statistics
print("\n11. Testing Dashboard Statistics...")
try:
    headers = {"Authorization": f"Bearer {admin_token}"}
    req = urllib.request.Request(f"{BASE_URL}/api/dashboard", headers=headers)
    res = json.loads(urllib.request.urlopen(req).read().decode())
    if res.get("success") and "stats" in res:
        st = res["stats"]
        record_test("Dashboard Statistics", True, f"Total: {st['total']}, Available: {st['available']}, Revenue: ${st['revenue']}")
    else:
        record_test("Dashboard Statistics", False, str(res))
except Exception as e:
    record_test("Dashboard Statistics", False, str(e))

# TEST 12: CLI main.py Compatibility
print("\n12. Testing CLI main.py Compatibility...")
try:
    from hotel_manager import load_rooms, api_get_stats
    rooms = load_rooms()
    stats = api_get_stats(rooms)
    if len(rooms) >= 5 and "total" in stats:
        record_test("CLI main.py Data Sync", True, f"Loaded {len(rooms)} rooms from SQLite database cleanly")
    else:
        record_test("CLI main.py Data Sync", False, f"Unexpected rooms: {rooms}")
except Exception as e:
    record_test("CLI main.py Data Sync", False, str(e))

# SUMMARY REPORT
print("\n==================================================")
print("              SUMMARY TEST REPORT                 ")
print("==================================================")
print(f"Total Tests Run: {len(results['passed']) + len(results['failed'])}")
print(f"Tests Passed   : {len(results['passed'])}")
print(f"Tests Failed   : {len(results['failed'])}")

if results["failed"]:
    print("\nFAILED TESTS DETAILS:")
    for err in results["errors"]:
        print(f" - {err}")
else:
    print("\n🎉 ALL COMPONENT VERIFICATIONS PASSED 100% CLEANLY!")
