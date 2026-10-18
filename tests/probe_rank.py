import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from kb.server import DIM, features, normalize

docs = [json.loads(line) for line in (ROOT / "fixtures" / "kb-corpus.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
raw = []
for doc in docs:
    raw.append({**doc, "tf": features(((doc["title"] + "\n") * 3) + doc["text"])})
df = [0] * DIM
for doc in raw:
    for index, value in enumerate(doc["tf"]):
        if value:
            df[index] += 1
total = len(raw)
idf = [math.log((total + 1) / (df[i] + 1)) + 1 for i in range(DIM)]
built = []
for doc in raw:
    vec = normalize([doc["tf"][i] * idf[i] for i in range(DIM)])
    built.append((doc["doc_id"], doc["title"], vec))
prompts = [json.loads(line) for line in (ROOT / "fixtures" / "prompts-1000.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
hit = 0
miss = []
for item in prompts:
    qv = normalize([a * b for a, b in zip(features(item["prompt"]), idf)])
    best = None
    best_score = -1
    for doc_id, title, vec in built:
        score = sum(a * b for a, b in zip(qv, vec))
        if score > best_score or (score == best_score and (best is None or doc_id < best)):
            best_score = score
            best = doc_id
    if best == item["doc_id"]:
        hit += 1
    elif len(miss) < 8:
        miss.append((item["doc_id"], best, item["title"]))
print(f"hit {hit}/{len(prompts)} miss {miss}")
