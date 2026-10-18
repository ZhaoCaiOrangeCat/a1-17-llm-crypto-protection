import json
from pathlib import Path

root = Path(r"C:\Users\zhaoc\Desktop\密码")
rows = [
    json.loads(line)
    for line in (root / "data" / "raw" / "m5-balanced.jsonl").read_text(encoding="utf-8").splitlines()
    if line.strip()
]
prompts = [
    json.loads(line)
    for line in (root / "fixtures" / "prompts-1000.jsonl").read_text(encoding="utf-8").splitlines()
    if line.strip()
]
docs = {}
for line in (root / "fixtures" / "kb-corpus.jsonl").read_text(encoding="utf-8").splitlines():
    if line.strip():
        doc = json.loads(line)
        docs[doc["doc_id"]] = doc

fail = [row for row in rows if not row["ok"]]
over = [row for row in rows if row["delta"] > 30]
print("n", len(rows), "fail", len(fail), "over30", len(over))
print("delta mean", round(sum(row["delta"] for row in rows) / len(rows), 1))
print("off-on mean", round(sum(row["delta_off_on"] for row in rows) / len(rows), 1))
print("on-off mean", round(sum(row["delta_on_off"] for row in rows) / len(rows), 1))

runs = []
current = 0
for row in rows:
    if not row["ok"]:
        current += 1
    else:
        if current:
            runs.append(current)
        current = 0
if current:
    runs.append(current)
print("fail_runs", runs)

over_runs = []
current = 0
for row in rows:
    if row["delta"] > 30:
        current += 1
    else:
        if current:
            over_runs.append(current)
        current = 0
if current:
    over_runs.append(current)
print("over30_runs", "max", max(over_runs) if over_runs else 0, "n_runs", len(over_runs))

print("FAIL")
for row in fail:
    prompt = prompts[row["i"]]
    doc = docs[prompt["doc_id"]]
    limit = 0.15 * row["t_off"]
    print(
        f"  i={row['i']} chars={len(prompt['prompt'])} text={len(doc['text'])} "
        f"off={row['t_off']} on={row['t_on']} d={row['delta']} "
        f"off_on={row['delta_off_on']} on_off={row['delta_on_off']} lim={limit:.1f}"
    )

deltas = sorted(row["delta"] for row in over)
if deltas:
    print(
        "over30 p50", round(deltas[len(deltas) // 2], 1),
        "p90", round(deltas[int(0.9 * (len(deltas) - 1))], 1),
        "max", round(deltas[-1], 1),
    )

def mean(items, key):
    return sum(item[key] for item in items) / len(items)

rest = [row for row in rows if row["delta"] <= 30]
print("over chars", round(mean([{**row, "chars": len(prompts[row["i"]]["prompt"])} for row in over], "chars"), 1))
print("rest chars", round(mean([{**row, "chars": len(prompts[row["i"]]["prompt"])} for row in rest], "chars"), 1))
print("over off", round(mean(over, "t_off"), 1), "rest off", round(mean(rest, "t_off"), 1))
