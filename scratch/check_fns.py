import re

with open("app.js", "r", encoding="utf-8") as f:
    app_js = f.read()

with open("index.html", "r", encoding="utf-8") as f:
    index_html = f.read()

# Find all onclick attributes
onclicks = re.findall(r'onclick=["\']([^"\']+)["\']', index_html)
fn_calls = set()
for oc in onclicks:
    # Extract function name
    matches = re.findall(r'([a-zA-Z0-9_$]+)\s*\(', oc)
    for m in matches:
        if m not in ('preventDefault', 'stopPropagation', 'alert', 'confirm', 'event'):
            fn_calls.add(m)

print(f"Total onclick functions called from index.html: {len(fn_calls)}")
missing_fns = []
for fn in sorted(fn_calls):
    if not re.search(rf'function\s+{re.escape(fn)}\b', app_js) and not re.search(rf'\b{re.escape(fn)}\s*=', app_js):
        missing_fns.append(fn)

print(f"Missing functions in app.js ({len(missing_fns)}):")
for mf in missing_fns:
    print(" -", mf)
