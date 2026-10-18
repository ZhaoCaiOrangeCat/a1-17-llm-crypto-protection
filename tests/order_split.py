import json
from pathlib import Path

rows = [
    json.loads(line)
    for line in Path(r"C:\Users\zhaoc\Desktop\密码\data\raw\m5.jsonl").read_text(encoding="utf-8").splitlines()
    if line.strip()
]
print("lines", len(rows), "order", rows[0].get("order"), rows[2].get("order") if len(rows) > 2 else None)
groups = {"off-on": [], "on-off": []}
index = 0
while index < len(rows) - 1:
    off, on = rows[index], rows[index + 1]
    delta = on["latency_ms"] - off["latency_ms"]
    ok = delta <= 30 or delta <= 0.15 * off["latency_ms"]
    groups[off.get("order") or "off-on"].append((off["latency_ms"], on["latency_ms"], delta, ok))
    index += 2
for name, items in groups.items():
    if not items:
        continue
    passed = sum(1 for item in items if item[3])
    print(
        name,
        "n", len(items),
        "pass", passed,
        "off", round(sum(item[0] for item in items) / len(items), 1),
        "on", round(sum(item[1] for item in items) / len(items), 1),
        "delta", round(sum(item[2] for item in items) / len(items), 1),
    )
