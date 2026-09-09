import re

with open("app.js", "r", encoding="utf-8") as f:
    app_js = f.read()

# Find all onclick attributes inside strings in app.js
onclicks = re.findall(r'onclick=[\"\']([^\"\']+)[\"\']', app_js)
fn_calls = set()
for oc in onclicks:
    matches = re.findall(r'([a-zA-Z0-9_$]+)\s*\(', oc)
    for m in matches:
        if m not in ('preventDefault', 'stopPropagation', 'alert', 'confirm', 'event', 'closeDrawer', 'openDrawer', 'openModal', 'closeModal', 'showToast'):
            fn_calls.add(m)

missing = []
for fn in sorted(fn_calls):
    if not re.search(rf'function\s+{re.escape(fn)}\b', app_js) and not re.search(rf'\b{re.escape(fn)}\s*=', app_js):
        missing.append(fn)

print(f"Functions referenced in app.js dynamic HTML ({len(fn_calls)}):")
for f in sorted(fn_calls):
    print(f"  {f}: {'EXISTS' if f not in missing else 'MISSING'}")

if missing:
    print(f"MISSING: {missing}")
else:
    print("ALL dynamic HTML onclick functions exist in app.js!")
