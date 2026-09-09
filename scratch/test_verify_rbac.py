import urllib.request
import urllib.parse
import json
import sys

BASE_URL = "http://127.0.0.1:5000"

def make_req(path, method="GET", data=None, token=None, custom_headers=None):
    url = f"{BASE_URL}{path}"
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if custom_headers:
        headers.update(custom_headers)
    
    body = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            status = resp.status
            content = resp.read().decode("utf-8")
            try:
                parsed = json.loads(content)
            except Exception:
                parsed = content
            return status, parsed
    except urllib.error.HTTPError as e:
        content = e.read().decode("utf-8")
        try:
            parsed = json.loads(content)
        except Exception:
            parsed = content
        return e.code, parsed
    except Exception as e:
        return 500, {"error": str(e)}


def run_tests():
    print("\n" + "="*70)
    print(" HOTEL MANAGEMENT SYSTEM - ACCESS & RBAC VERIFICATION SUITE")
    print("="*70)
    
    tests_passed = 0
    tests_failed = 0
    
    def assert_check(name, condition, details=""):
        nonlocal tests_passed, tests_failed
        if condition:
            print(f"  ✅ PASS: {name}")
            tests_passed += 1
        else:
            print(f"  ❌ FAIL: {name} | {details}")
            tests_failed += 1

    # 1. Login as Admin
    st, res = make_req("/api/auth/login", method="POST", data={"username": "admin", "password": "admin123"})
    assert_check("Admin Login", st == 200 and res.get("success"), f"Status: {st}, Res: {res}")
    admin_token = res["user"]["token"]
    
    # 2. Login as Receptionist
    st, res = make_req("/api/auth/login", method="POST", data={"username": "reception", "password": "rec123"})
    assert_check("Receptionist Login", st == 200 and res.get("success"), f"Status: {st}, Res: {res}")
    rec_token = res["user"]["token"]
    
    # 3. Login as Housekeeping
    st, res = make_req("/api/auth/login", method="POST", data={"username": "cleaner", "password": "clean123"})
    assert_check("Housekeeping Login", st == 200 and res.get("success"), f"Status: {st}, Res: {res}")
    hk_token = res["user"]["token"]

    print("\n--- Testing Receptionist Operations (Previously Denied) ---")
    # Receptionist: Rooms access
    st, res = make_req("/api/rooms", token=rec_token)
    assert_check("Receptionist GET /api/rooms (was 403)", st == 200 and res.get("success"), f"Status: {st}")

    # Receptionist: Housekeeping access
    st, res = make_req("/api/housekeeping", token=rec_token)
    assert_check("Receptionist GET /api/housekeeping (was 403)", st == 200 and res.get("success"), f"Status: {st}")

    # Receptionist: Update Housekeeping
    st, res = make_req("/api/housekeeping", method="PUT", data={"room_number": "101", "cleaning_status": "Clean", "notes": "Frontdesk inspected"}, token=rec_token)
    assert_check("Receptionist PUT /api/housekeeping (was 403)", st == 200 and res.get("success"), f"Status: {st}")

    # Receptionist: POST Housekeeping (previously 405)
    st, res = make_req("/api/housekeeping", method="POST", data={"room_number": "101", "cleaning_status": "Clean", "notes": "Frontdesk inspected via POST"}, token=rec_token)
    assert_check("Receptionist POST /api/housekeeping (was 405)", st == 200 and res.get("success"), f"Status: {st}")

    # Receptionist: Guests access
    st, res = make_req("/api/guests", token=rec_token)
    assert_check("Receptionist GET /api/guests", st == 200 and res.get("success"), f"Status: {st}")

    # Receptionist: Bookings access
    st, res = make_req("/api/bookings", token=rec_token)
    assert_check("Receptionist GET /api/bookings", st == 200 and res.get("success"), f"Status: {st}")

    # Receptionist: Services access
    st, res = make_req("/api/services", token=rec_token)
    assert_check("Receptionist GET /api/services", st == 200 and res.get("success"), f"Status: {st}")

    # Receptionist: Payments access
    st, res = make_req("/api/payments", token=rec_token)
    assert_check("Receptionist GET /api/payments", st == 200 and res.get("success"), f"Status: {st}")

    # Receptionist: Blocked from Admin Users management
    st, res = make_req("/api/auth/users", token=rec_token)
    assert_check("Receptionist blocked from /api/auth/users (403)", st == 403, f"Status: {st}")

    # Receptionist: Blocked from POST /api/rooms (Creating physical rooms is Admin/Manager only)
    st, res = make_req("/api/rooms", method="POST", data={"room_number": "NO-AUTH-101"}, token=rec_token)
    assert_check("Receptionist blocked from POST /api/rooms (403)", st == 403, f"Status: {st}")

    print("\n--- Testing Housekeeping Operations (Previously Denied) ---")
    # Housekeeping: Rooms
    st, res = make_req("/api/rooms", token=hk_token)
    assert_check("Housekeeping GET /api/rooms", st == 200 and res.get("success"), f"Status: {st}")

    # Housekeeping: Update Room cleaning
    st, res = make_req("/api/housekeeping", method="PUT", data={"room_number": "102", "cleaning_status": "Cleaning", "notes": "In progress"}, token=hk_token)
    assert_check("Housekeeping PUT /api/housekeeping", st == 200 and res.get("success"), f"Status: {st}")

    # Housekeeping: Blocked from Bookings directory
    st, res = make_req("/api/bookings", token=hk_token)
    assert_check("Housekeeping blocked from GET /api/bookings (403)", st == 403, f"Status: {st}")

    # Housekeeping: Blocked from Users
    st, res = make_req("/api/auth/users", token=hk_token)
    assert_check("Housekeeping blocked from /api/auth/users (403)", st == 403, f"Status: {st}")

    print("\n--- Testing Token Parsing Resiliency ---")
    # Lowercase bearer
    st, res = make_req("/api/auth/me", custom_headers={"Authorization": f"bearer {rec_token}"})
    assert_check("Authorization with lowercase 'bearer'", st == 200 and res.get("success"), f"Status: {st}")

    # X-Auth-Token header
    st, res = make_req("/api/auth/me", custom_headers={"X-Auth-Token": rec_token})
    assert_check("Header 'X-Auth-Token'", st == 200 and res.get("success"), f"Status: {st}")

    # Query param ?token=
    st, res = make_req(f"/api/auth/me?token={rec_token}")
    assert_check("Query parameter '?token='", st == 200 and res.get("success"), f"Status: {st}")

    # Invalid token gives 401
    st, res = make_req("/api/auth/me", token="bogus_token_12345")
    assert_check("Bogus token returns 401 Unauthorized", st == 401, f"Status: {st}")

    print("\n" + "="*70)
    print(f" RESULTS: {tests_passed} PASSED, {tests_failed} FAILED")
    print("="*70)
    
    if tests_failed > 0:
        sys.exit(1)

if __name__ == "__main__":
    run_tests()
