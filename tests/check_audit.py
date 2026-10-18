import json
import sys
from pathlib import Path

sys.path.insert(0, r"C:\Users\zhaoc\Desktop\密码\src")
from common.crypto import sm3_digest
from common.frame import canon

chain_path = Path(r"C:\Users\zhaoc\Desktop\密码\data\runs\20261017-011955\chain.jsonl")
m1_path = Path(r"C:\Users\zhaoc\Desktop\密码\data\raw\m1.jsonl")
rows = [json.loads(line) for line in chain_path.read_text(encoding="utf-8").splitlines() if line.strip()]
prev = b"\x00" * 32
bad = 0
checkpoints = 0
nodes = {}
for index, row in enumerate(rows, start=1):
    digest = sm3_digest(prev + canon(row["record"]))
    if digest.hex() != row["hash"] or row["n"] != index:
        bad += 1
        if bad <= 3:
            print("break", index)
    if index % 100 == 0:
        if row.get("checkpoint"):
            checkpoints += 1
        else:
            print("missing checkpoint", index)
    prev = digest
    node = row["record"].get("node", "?")
    nodes[node] = nodes.get(node, 0) + 1
m1 = [json.loads(line) for line in m1_path.read_text(encoding="utf-8").splitlines() if line.strip()]
hashes = {row["hash"] for row in rows}
missing = [row["audit_hash"] for row in m1 if row["audit_hash"] not in hashes]
plain = sum(1 for row in rows if "prompt" in row["record"] or "content" in row["record"])
print("rows", len(rows), "bad", bad, "checkpoints", checkpoints, "nodes", nodes)
print("m1_missing", len(missing), "plaintext_fields", plain)
print("tail", rows[-1]["hash"])
