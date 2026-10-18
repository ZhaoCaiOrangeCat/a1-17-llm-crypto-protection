import json
from pathlib import Path

rows = [
    json.loads(line)
    for line in Path(r"C:\Users\zhaoc\Desktop\密码\data\raw\m5.jsonl").read_text(encoding="utf-8").splitlines()
    if line.strip()
]
pairs = []
index = 0
while index < len(rows) - 1:
    off, on = rows[index], rows[index + 1]
    delta = on["latency_ms"] - off["latency_ms"]
    limit = 0.15 * off["latency_ms"]
    pairs.append(
        {
            "i": len(pairs),
            "off": off["latency_ms"],
            "on": on["latency_ms"],
            "delta": delta,
            "limit": limit,
            "le30": delta <= 30,
            "le15": delta <= limit,
            "ok": delta <= 30 or delta <= limit,
        }
    )
    index += 2

fail = [item for item in pairs if not item["ok"]]
over30 = [item for item in pairs if item["delta"] > 30]
print("pairs", len(pairs), "fail", len(fail), "over30", len(over30))
print("FAIL")
for item in fail:
    print(
        f"  i={item['i']} off={item['off']:.1f} on={item['on']:.1f} "
        f"d={item['delta']:.1f} lim15={item['limit']:.1f}"
    )

runs = []
current = 0
for item in pairs:
    if item["delta"] > 30:
        current += 1
    else:
        if current:
            runs.append(current)
        current = 0
if current:
    runs.append(current)
print("over30_runs", runs, "max_run", max(runs) if runs else 0)

fail_runs = []
current = 0
for item in pairs:
    if not item["ok"]:
        current += 1
    else:
        if current:
            fail_runs.append(current)
        current = 0
if current:
    fail_runs.append(current)
print("fail_runs", fail_runs)

deltas = sorted(item["delta"] for item in over30)
print(
    "over30_min", round(deltas[0], 1),
    "p50", round(deltas[len(deltas) // 2], 1),
    "p90", round(deltas[int(0.9 * (len(deltas) - 1))], 1),
    "max", round(deltas[-1], 1),
)
print("top")
for item in sorted(pairs, key=lambda row: -row["delta"])[:12]:
    print(
        f"  i={item['i']} off={item['off']:.1f} on={item['on']:.1f} "
        f"d={item['delta']:.1f} lim15={item['limit']:.1f} ok={item['ok']}"
    )
