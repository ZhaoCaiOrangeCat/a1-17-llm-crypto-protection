import json
from pathlib import Path

root = Path(r"C:\Users\zhaoc\Desktop\密码")
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
rows = [
    json.loads(line)
    for line in (root / "data" / "raw" / "m5.jsonl").read_text(encoding="utf-8").splitlines()
    if line.strip()
]
pairs = []
index = 0
while index < len(rows) - 1:
    off, on = rows[index], rows[index + 1]
    prompt = prompts[len(pairs)]
    doc = docs[prompt["doc_id"]]
    delta = on["latency_ms"] - off["latency_ms"]
    pairs.append(
        {
            "i": len(pairs),
            "chars": len(prompt["prompt"]),
            "title": len(prompt["title"]),
            "text": len(doc["text"]),
            "off": off["latency_ms"],
            "delta": delta,
            "over": delta > 30,
            "fail": not (delta <= 30 or delta <= 0.15 * off["latency_ms"]),
        }
    )
    index += 2


def mean(items, key):
    return sum(item[key] for item in items) / len(items)


over = [item for item in pairs if item["over"]]
rest = [item for item in pairs if not item["over"]]
print("n", len(pairs))
print("over chars", round(mean(over, "chars"), 1), "rest", round(mean(rest, "chars"), 1))
print("over title", round(mean(over, "title"), 1), "rest", round(mean(rest, "title"), 1))
print("over text", round(mean(over, "text"), 1), "rest", round(mean(rest, "text"), 1))
print("over off", round(mean(over, "off"), 1), "rest", round(mean(rest, "off"), 1))
widths = {}
for item in pairs:
    bucket = item["chars"]
    widths.setdefault(bucket, []).append(item)
print("by prompt chars")
for chars in sorted(widths):
    group = widths[chars]
    overs = sum(1 for item in group if item["over"])
    fails = sum(1 for item in group if item["fail"])
    print(
        f"  chars={chars:3d} n={len(group):4d} over30={overs:3d} fail={fails} "
        f"delta={mean(group, 'delta'):6.1f} off={mean(group, 'off'):6.1f}"
    )
fail = next(item for item in pairs if item["fail"])
print("fail", {key: fail[key] for key in ("i", "chars", "title", "text", "off", "delta")})
