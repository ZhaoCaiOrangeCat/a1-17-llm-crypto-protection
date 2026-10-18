import json
import statistics
import time
from pathlib import Path

import sys
sys.path.insert(0, r"C:\Users\zhaoc\Desktop\密码\src")
from common.crypto import sm3_digest, wrap_key, unwrap_key
from common.frame import open_frame, seal

root = Path(r"C:\Users\zhaoc\Desktop\密码")
prompt = json.loads((root / "fixtures" / "prompts-1000.jsonl").read_text(encoding="utf-8").splitlines()[0])
doc = json.loads((root / "fixtures" / "kb-corpus.jsonl").read_text(encoding="utf-8").splitlines()[0])
prompt_b = prompt["prompt"].encode("utf-8")
query_b = prompt_b
tool_b = json.dumps({"city": "北京"}, ensure_ascii=False).encode("utf-8")
retrieval_b = json.dumps(
    [{"doc_id": doc["doc_id"], "title": doc["title"], "text": doc["text"][:80], "score": 0.5}],
    ensure_ascii=False,
).encode("utf-8")
output_b = ("根据资料，" + doc["title"] + "。" * 40).encode("utf-8")[:240]
dek = b"0123456789abcdef"
parent = b"abcdef0123456789"
print("bytes", len(prompt_b), len(tool_b), len(retrieval_b), len(output_b))


def once():
    t0 = time.perf_counter()
    wrapped = wrap_key(parent, dek)
    unwrap_key(parent, wrapped)
    frames = [
        seal(dek, "prompt", "tenant-a", "r", 1, prompt_b),
        seal(dek, "query", "tenant-a", "r", 1, query_b),
        seal(dek, "tool_arg", "tenant-a", "r", 1, tool_b),
        seal(dek, "retrieval", "tenant-a", "r", 1, retrieval_b),
        seal(dek, "output", "tenant-a", "r", 1, output_b),
    ]
    for frame in frames:
        open_frame(dek, frame)
    sm3_digest(b"audit-record")
    return (time.perf_counter() - t0) * 1000


for _ in range(10):
    once()
samples = [once() for _ in range(100)]
print("crypto_ms median", round(statistics.median(samples), 2), "p95", round(sorted(samples)[94], 2), "max", round(max(samples), 2))
