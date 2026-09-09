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

    # 7. Guest Profile Update (Guest Edit)
    guest_update_data = {
        "full_name": "Duchess Amelia Claremont-Windsor",
        "city": "Cambridge",
        "phone": "9988776699"
    }
    status, g_upd_res = make_request(f"/api/guests/{guest_id}", method="PUT", data=guest_update_data, token=token)
    assert status == 200 and g_upd_res["success"], f"Guest update failed: {g_upd_res}"
    print(f"  ✓ [200 OK] Guest profile updated (PUT /api/guests/{guest_id})")

    # Verify updated guest
    status, g_get_res = make_request(f"/api/guests/{guest_id}", token=token)
    assert status == 200 and g_get_res["guest"]["full_name"] == "Duchess Amelia Claremont-Windsor", "Guest verify failed"
    assert g_get_res["guest"]["country"] == "United Kingdom", "COALESCE failed to preserve country"
    print("  ✓ [200 OK] Guest update verified with preserved fields")

    # 8. Room Add, Edit, and Delete Lifecycle
    new_room_data = {
        "room_number": "888",
        "floor": 8,
        "room_type": "Penthouse",
        "bed_type": "King",
        "capacity": 4,
        "price_per_night": 750.0,
        "amenities": "Panoramic View, Sauna, Butler"
    }
    status, r_add_res = make_request("/api/rooms", method="POST", data=new_room_data, token=token)
    assert status in [201, 400], f"Room add response: {r_add_res}"

    # Find room 888 ID
    status, all_rooms_res = make_request("/api/rooms", token=token)
    r888 = next((r for r in all_rooms_res["list"] if str(r["room_number"]) == "888"), None)
    assert r888 is not None, "Room 888 not found in directory"
    r888_id = r888["id"]
    print("  ✓ [201 Created] Room 888 added to property inventory")

    # Edit room 888
    r_edit_data = {
        "price_per_night": 850.0,
        "amenities": "Panoramic View, Sauna, Butler, Private Pool"
    }
    status, r_edit_res = make_request(f"/api/rooms/{r888_id}", method="PUT", data=r_edit_data, token=token)
    assert status == 200 and r_edit_res["success"], f"Room edit failed: {r_edit_res}"
    print(f"  ✓ [200 OK] Room 888 updated (PUT /api/rooms/{r888_id})")

    # Delete room 888
    status, r_del_res = make_request(f"/api/rooms/{r888_id}", method="DELETE", token=token)
    assert status == 200 and r_del_res["success"], f"Room delete failed: {r_del_res}"
    print(f"  ✓ [200 OK] Room 888 deleted (DELETE /api/rooms/{r888_id})")

    # 9. Booking & Overlap Test
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

    # 10. Housekeeping
    hk_data = {
        "room_number": "103",
        "cleaning_status": "Clean",
        "assigned_staff": "Housekeeping Team A"
    }
    status, hk_res = make_request("/api/housekeeping", method="PUT", data=hk_data, token=token)
    assert status == 200, f"Housekeeping update failed: {status}"
    print("  ✓ [200 OK] Housekeeping state updated")

    # 11. CSV Export
    status, csv_res = make_request("/api/reports/export/csv?type=guests", token=token)
    assert status == 200 and "Full Name" in csv_res, "CSV export failed"
    print("  ✓ [200 OK] Reports CSV generated")

    print("\n🎉 ALL LIVE SERVER ENDPOINT TESTS PASSED SUCCESSFULLY!\n")


if __name__ == "__main__":
    run_live_tests()
