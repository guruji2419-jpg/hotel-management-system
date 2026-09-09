"""
test_browser_cdp.py
-------------------
End-to-end browser automation using Chrome DevTools Protocol (CDP) via Edge.
Validates the actual UI, DOM, JavaScript runtime execution, console errors, and full user lifecycle.
"""

import subprocess
import time
import json
import urllib.request
import asyncio
import os
import shutil
import tempfile
import websockets

EDGE_PATH = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
CDP_PORT = 9222
BASE_URL = "http://127.0.0.1:5000"

async def run_cdp_test():
    user_data_dir = tempfile.mkdtemp(prefix="edge_cdp_")
    
    # 1. Launch Edge in headless mode with remote debugging
    cmd = [
        EDGE_PATH,
        f"--remote-debugging-port={CDP_PORT}",
        f"--user-data-dir={user_data_dir}",
        "--headless=new",
        "--disable-gpu",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-background-networking",
        "about:blank"
    ]
    
    print("🚀 Launching Edge browser via CDP...")
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    
    ws_url = None
    for _ in range(20):
        await asyncio.sleep(0.5)
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{CDP_PORT}/json") as r:
                pages = json.loads(r.read().decode())
                if pages:
                    ws_url = pages[0]["webSocketDebuggerUrl"]
                    break
        except Exception:
            pass

    if not ws_url:
        proc.kill()
        shutil.rmtree(user_data_dir, ignore_errors=True)
        raise RuntimeError("Failed to connect to Edge CDP endpoint")

    print(f"🔌 Connected to Browser CDP at {ws_url}")

    msg_id = 0
    console_messages = []
    page_errors = []

    async with websockets.connect(ws_url) as ws:
        async def send(method, params=None):
            nonlocal msg_id
            msg_id += 1
            payload = {"id": msg_id, "method": method, "params": params or {}}
            await ws.send(json.dumps(payload))
            while True:
                raw = await ws.recv()
                msg = json.loads(raw)
                if msg.get("method") == "Runtime.consoleAPICalled":
                    text = " ".join([arg.get("value", "") for arg in msg["params"].get("args", []) if "value" in arg])
                    console_messages.append(f"[{msg['params']['type']}] {text}")
                elif msg.get("method") == "Runtime.exceptionThrown":
                    page_errors.append(msg["params"]["exceptionDetails"]["text"])
                elif msg.get("id") == payload["id"]:
                    return msg.get("result", {})

        async def evaluate(expr):
            res = await send("Runtime.evaluate", {
                "expression": expr,
                "returnByValue": True,
                "awaitPromise": True
            })
            if "exceptionDetails" in res:
                page_errors.append(str(res["exceptionDetails"]))
            result_obj = res.get("result", {})
            return result_obj.get("value")

        # Enable runtime & page events
        await send("Page.enable")
        await send("Runtime.enable")

        print("🌐 Navigating to http://127.0.0.1:5000...")
        await send("Page.navigate", {"url": BASE_URL})
        
        # Wait until document is interactive/complete
        for _ in range(20):
            await asyncio.sleep(0.5)
            state = await evaluate("document.readyState")
            if state in ["interactive", "complete"]:
                break

        # Ensure fresh state
        await evaluate("localStorage.clear(); currentToken = ''; currentUser = null; showAuthScreen(true);")
        await asyncio.sleep(0.5)

        # 1. Verify Login Screen
        auth_visible = await evaluate("!document.getElementById('auth-screen').classList.contains('hidden')")
        print(f"  ✓ Step 1: Login Screen visible: {auth_visible}")
        assert auth_visible, "Login screen should be visible initially"

        # 2. Perform Login as Admin
        print("🔐 Step 2: Logging in as Admin...")
        login_res = await evaluate("""
        (async () => {
            document.getElementById('login-user').value = 'admin';
            document.getElementById('login-pass').value = 'admin123';
            const form = document.getElementById('form-login');
            form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
            await new Promise(r => setTimeout(r, 1000));
            return {
                token: currentToken,
                user: currentUser ? currentUser.full_name : null,
                appVisible: document.getElementById('app-wrapper').classList.contains('visible')
            };
        })()
        """)
        print(f"  ✓ Login result: {login_res}")
        assert login_res["token"], "Session token must be populated"
        assert login_res["appVisible"], "App wrapper must be visible"

        # 3. Check Dashboard KPIs
        await asyncio.sleep(1)
        dash_stats = await evaluate("""
        ({
            total: document.getElementById('d-total')?.textContent,
            available: document.getElementById('d-available')?.textContent,
            occupied: document.getElementById('d-occupied')?.textContent,
            revenue: document.getElementById('d-revenue')?.textContent
        })
        """)
        print(f"  ✓ Step 3: Dashboard KPIs: {dash_stats}")
        assert dash_stats["total"] is not None, "Dashboard total rooms should render"

        # 4. Navigate to Rooms Directory
        print("🏨 Step 4: Navigating to Rooms Directory...")
        await evaluate("switchView('rooms');")
        await asyncio.sleep(1)
        rooms_count = await evaluate("document.querySelectorAll('.room-lux-card').length")
        print(f"  ✓ Step 5: Rooms Directory loaded with {rooms_count} room cards")
        assert rooms_count > 0, "Rooms cards must render in directory"

        # 5. Test Guided Check-in: Click Check-In on an available room
        print("🛎️ Step 6: Testing startCheckInForRoom('101')...")
        checkin_prep = await evaluate("""
        (() => {
            startCheckInForRoom('101');
            const step1Active = document.getElementById('ci-step-1').classList.contains('active');
            const roomVal = document.getElementById('wiz-ci-room').value;
            const guestVal = document.getElementById('wiz-ci-guest').value;
            return { step1Active, roomVal, guestVal };
        })()
        """)
        await asyncio.sleep(0.5)
        print(f"  ✓ Step 1 Wizard Active: {checkin_prep['step1Active']}, Room: '{checkin_prep['roomVal']}', Guest: '{checkin_prep['guestVal']}'")
        assert checkin_prep["step1Active"], "Check-in wizard must remain on Step 1 without premature errors"

        # 6. Fill in Guest Name and Proceed
        print("👤 Step 7: Entering guest name and advancing steps...")
        step2_res = await evaluate("""
        (() => {
            document.getElementById('wiz-ci-guest').value = 'Baron Alexander Sterling';
            nextCheckInStep(2);
            return {
                step2Active: document.getElementById('ci-step-2').classList.contains('active'),
                selectedRoom: document.getElementById('wiz-ci-room').value
            };
        })()
        """)
        print(f"  ✓ Step 2 Active: {step2_res['step2Active']}, Selected Room: {step2_res['selectedRoom']}")
        assert step2_res["step2Active"], "Step 2 should be active"

        # Advance to Step 3 and set nights = 2
        step3_res = await evaluate("""
        (() => {
            nextCheckInStep(3);
            document.getElementById('wiz-ci-nights').value = '2';
            return {
                step3Active: document.getElementById('ci-step-3').classList.contains('active')
            };
        })()
        """)
        print(f"  ✓ Step 3 Active: {step3_res['step3Active']}")

        # Advance to Step 4 and verify Summary
        step4_res = await evaluate("""
        (() => {
            nextCheckInStep(4);
            const summary = document.getElementById('wiz-ci-summary').textContent;
            return {
                step4Active: document.getElementById('ci-step-4').classList.contains('active'),
                summary: summary
            };
        })()
        """)
        print(f"  ✓ Step 4 Active: {step4_res['step4Active']}, Summary text: {step4_res['summary'][:120]}...")
        assert "Estimated Tax (12%)" in step4_res["summary"], "Step 4 must show 12% tax"
        assert "Estimated Grand Total" in step4_res["summary"], "Step 4 must show estimated grand total"

        # 7. Complete Check-In
        print("🔑 Step 8: Submitting check-in form...")
        ci_submit = await evaluate("""
        (async () => {
            const form = document.getElementById('wizard-checkin-form');
            form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
            await new Promise(r => setTimeout(r, 1500));
            const room101 = allRooms.find(r => String(r.room_number) === '101');
            return {
                room101Status: room101 ? room101.status : null
            };
        })()
        """)
        print(f"  ✓ Check-in complete. Room 101 status: {ci_submit['room101Status']}")
        assert ci_submit["room101Status"] == "Occupied", "Room 101 status must update to Occupied"

        # 8. Check-Out and Printable Invoice
        print("🧾 Step 9: Triggering Check-Out for Room 101...")
        co_res = await evaluate("""
        (async () => {
            // Trigger check-out API directly via fetch
            const res = await fetch('/api/check-out', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${currentToken}` },
                body: JSON.stringify({ room_num: '101', services: 0.0 })
            });
            const data = await res.json();
            if (data.invoice) {
                renderPrintableInvoice(data.invoice);
            }
            await syncState(false);
            const room101 = allRooms.find(r => String(r.room_number) === '101');
            const invModalOpen = document.getElementById('modal-invoice').classList.contains('active');
            const invNumber = document.getElementById('inv-render-number')?.textContent;
            return {
                checkoutSuccess: data.success,
                room101Status: room101 ? room101.status : null,
                invModalOpen,
                invNumber
            };
        })()
        """)
        print(f"  ✓ Check-out result: {co_res}")
        assert co_res["checkoutSuccess"], "Check-out must succeed"
        assert co_res["room101Status"] == "Cleaning", "Room 101 must transition to Cleaning"
        assert co_res["invModalOpen"], "Invoice modal must be displayed"

        # Close Invoice Modal
        await evaluate("closeModal('modal-invoice');")

        # 9. Housekeeping: Mark Room 101 Clean
        print("🧹 Step 10: Updating Housekeeping to Clean...")
        hk_res = await evaluate("""
        (async () => {
            await updateHKQuick('101', 'Clean');
            await syncState(false);
            const room101 = allRooms.find(r => String(r.room_number) === '101');
            return {
                room101Status: room101 ? room101.status : null,
                room101HK: room101 ? room101.housekeeping_status : null
            };
        })()
        """)
        print(f"  ✓ Housekeeping update result: {hk_res}")
        assert hk_res["room101Status"] == "Available", "Room 101 must transition back to Available"
        assert hk_res["room101HK"] == "Clean", "Room 101 housekeeping status must be Clean"

        # 10. Reports Canvas Visualization
        print("📊 Step 11: Loading Reports View...")
        await evaluate("switchView('reports');")
        await asyncio.sleep(1)
        reports_rendered = await evaluate("""
        (() => {
            const stats = document.getElementById('report-stats');
            const canvas = document.getElementById('chart-revenue');
            return {
                statsHasChildren: stats ? stats.children.length > 0 : false,
                canvasWidth: canvas ? canvas.width : 0
            };
        })()
        """)
        print(f"  ✓ Reports View loaded: {reports_rendered}")
        assert reports_rendered["statsHasChildren"], "Reports stats cards must render"
        assert reports_rendered["canvasWidth"] > 0, "Revenue canvas must initialize"

        # Check console logs and page errors
        print("\n📝 Browser Console Logs Collected:")
        for log in console_messages[-10:]:
            print(f"    {log}")

        print(f"\n🚨 Uncaught JavaScript Page Errors: {len(page_errors)}")
        if page_errors:
            for err in page_errors:
                print(f"    ❌ {err}")
        assert len(page_errors) == 0, f"No JavaScript page errors allowed: {page_errors}"

    proc.kill()
    shutil.rmtree(user_data_dir, ignore_errors=True)
    print("\n🎉 ALL BROWSER CDP UI WORKFLOW TESTS PASSED WITHOUT ERRORS!\n")

if __name__ == "__main__":
    asyncio.run(run_cdp_test())
