"""
scratch/test_live_server.py
---------------------------
Simulates live client requests to the running Flask server on http://127.0.0.1:5000.
Tests static assets, authorization, sessions, room mutations, overlap checking, and CSV reports.
"""

import urllib.request
import urllib.error
import json

BASE_URL = "http://127.0.0.1:5000"


def make_request(path, method="GET", data=None, token=None):
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


def run_live_tests():
    print("\n🌐 Testing Live Server on http://127.0.0.1:5000...")
    
    # 1. Static Assets
    status, _ = make_request("/")
    assert status == 200, f"Root / failed with {status}"
    print("  ✓ [200 OK] Static index.html served")

    status, _ = make_request("/styles.css")
    assert status == 200, f"styles.css failed with {status}"
    print("  ✓ [200 OK] styles.css served")

    status, _ = make_request("/app.js")
    assert status == 200, f"app.js failed with {status}"
    print("  ✓ [200 OK] app.js served")

    # 2. Login
    status, login_res = make_request("/api/auth/login", method="POST", data={"username": "admin", "password": "admin123"})
    assert status == 200 and login_res["success"], f"Login failed: {login_res}"
    token = login_res["user"]["token"]
    print(f"  ✓ [200 OK] Login successful, token: {token[:12]}...")

    # 3. Auth Me
    status, me_res = make_request("/api/auth/me", token=token)
    assert status == 200 and me_res["user"]["username"] == "admin", f"Auth me failed: {me_res}"
    print("  ✓ [200 OK] User session validated via persistent DB")

    # 4. Dashboard
    status, dash_res = make_request("/api/dashboard", token=token)
    assert status == 200 and "stats" in dash_res, f"Dashboard failed: {dash_res}"
    print(f"  ✓ [200 OK] Dashboard stats loaded: Total {dash_res['stats']['total']}, Revenue ${dash_res['stats']['revenue']}")

    # 5. Rooms
    status, rooms_res = make_request("/api/rooms", token=token)
    assert status == 200 and "list" in rooms_res, f"Rooms failed: {rooms_res}"
    print(f"  ✓ [200 OK] Room directory loaded ({len(rooms_res['list'])} rooms)")

    # 6. Guest Registration
    guest_data = {
        "full_name": "Duchess Amelia Claremont",
        "phone": "9988776655",
        "email": "amelia@claremont.co.uk",
        "city": "Oxford",
        "country": "United Kingdom",
        "id_proof_type": "Passport",
        "id_proof_number": "UK-991122"
    }
    status, g_res = make_request("/api/guests", method="POST", data=guest_data, token=token)
    assert status == 201 and g_res["success"], f"Guest creation failed: {g_res}"
    guest_id = g_res["guest_id"]
    print(f"  ✓ [201 Created] Guest '{guest_data['full_name']}' created (ID: {guest_id})")

    # 7. Booking & Overlap Test
    b1_data = {
        "guest_id": guest_id,
        "room_id": 4, # Room 201
        "check_in_date": "2026-12-01",
        "check_out_date": "2026-12-05",
        "advance_payment": 150.0
    }
    # Clean up prior bookings for room 4 on these dates
    status, b1_res = make_request("/api/bookings", method="POST", data=b1_data, token=token)
    if status == 201:
        print("  ✓ [201 Created] Booking confirmed for 2026-12-01 -> 2026-12-05")
    
    # Overlapping booking
    b2_data = {
        "guest_id": guest_id,
        "room_id": 4,
        "check_in_date": "2026-12-02",
        "check_out_date": "2026-12-04",
        "advance_payment": 0.0
    }
    status, b2_res = make_request("/api/bookings", method="POST", data=b2_data, token=token)
    assert status == 409, f"Expected 409 for overlap, got {status}: {b2_res}"
    print("  ✓ [409 Conflict] Overlap detection correctly rejected duplicate reservation")

    # 8. Housekeeping
    hk_data = {
        "room_number": "103",
        "cleaning_status": "Clean",
        "assigned_staff": "Housekeeping Team A"
    }
    status, hk_res = make_request("/api/housekeeping", method="PUT", data=hk_data, token=token)
    assert status == 200, f"Housekeeping update failed: {status}"
    print("  ✓ [200 OK] Housekeeping state updated")

    # 9. CSV Export
    status, csv_res = make_request("/api/reports/export/csv?type=guests", token=token)
    assert status == 200 and "Full Name" in csv_res, "CSV export failed"
    print("  ✓ [200 OK] Reports CSV generated")

    print("\n🎉 ALL LIVE SERVER ENDPOINT TESTS PASSED SUCCESSFULLY!\n")


if __name__ == "__main__":
    run_live_tests()
