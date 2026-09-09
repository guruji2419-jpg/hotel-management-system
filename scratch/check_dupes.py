import re
import json

def check_html():
    with open('index.html', encoding='utf-8') as f:
        html = f.read()
    
    ids = re.findall(r'id=["\']([^"\']+)["\']', html)
    from collections import Counter
    counts = Counter(ids)
    dupes = [k for k, v in counts.items() if v > 1]
    print(f"Duplicate IDs: {dupes}")

check_html()
