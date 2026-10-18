import json
from pathlib import Path

raw = Path(r"C:\Users\zhaoc\Desktop\密码\data\raw")
m1 = [json.loads(line) for line in (raw / "m1.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
m5 = [json.loads(line) for line in (raw / "m5.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
m7 = [json.loads(line) for line in (raw / "m7.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
m11 = [json.loads(line) for line in (raw / "m11.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
need = ["req_id", "t_start", "t_end", "latency_ms", "mode", "tenant_id", "key_ver", "result", "error_code", "prompt_sha256", "audit_hash"]
missing = [key for key in need if any(key not in row for row in m1)]
ok = sum(1 for row in m1 if row["result"] == "OK" and row["audit_hash"])
print("m1", len(m1), "ok", ok, "missing_fields", missing)
pairs = []
i = 0
while i < len(m5) - 1:
    off, on = m5[i], m5[i + 1]
    delta = on["latency_ms"] - off["latency_ms"]
    pairs.append((off["latency_ms"], delta, off["result"] == "OK" and on["result"] == "OK"))
    i += 2
via30 = sum(1 for off, delta, good in pairs if good and delta <= 30)
via15 = sum(1 for off, delta, good in pairs if good and delta > 30 and delta <= 0.15 * off)
fail = len(pairs) - via30 - via15
print("pairs", len(pairs), "le30", via30, "only15", via15, "fail", fail)
state_ok = sum(1 for row in m7 if row.get("state_ok"))
print("m7", len(m7), "state_ok", state_ok)
accepted = sum(1 for row in m11 if row.get("accepted"))
print("m11", len(m11), "accepted", accepted)
if m11:
    t0 = m11[0]["t0"]
    print("m11 span", round(min(row["t_req"] for row in m11) - t0, 2), round(max(row["t_req"] for row in m11) - t0, 2))
