import re

with open("app.js", "r", encoding="utf-8") as f:
    app_js = f.read()

with open("index.html", "r", encoding="utf-8") as f:
    index_html = f.read()

ids_in_js = set(re.findall(r'getElementById\(["\']([^"\']+)["\']\)', app_js))
print(f"Total getElementById in app.js: {len(ids_in_js)}")

missing = []
for el_id in sorted(ids_in_js):
    pattern = rf'id=["\']{re.escape(el_id)}["\']'
    if not re.search(pattern, index_html):
        missing.append(el_id)

print(f"Missing IDs in index.html ({len(missing)}):")
for m in missing:
    print(" -", m)
