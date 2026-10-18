import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from run_m1_m11 import ensure_llama, free_service_ports, load_prompts
from runtime import boot

N = 40
WARM = 8


def main():
    print("llama", ensure_llama(), flush=True)
    free_service_ports()
    env = boot(str(ROOT), "http://127.0.0.1:18080/v1/chat/completions", "qwen3.5-9b")
    prompts = load_prompts()
    term = env["a"]
    for item in prompts[:WARM]:
        term.infer(item["prompt"], protect=False)
        term.infer(item["prompt"], protect=True)
    qualified = 0
    fails = []
    hits = 0
    for index, item in enumerate(prompts[:N]):
        off = term.infer(item["prompt"], protect=False)
        on = term.infer(item["prompt"], protect=True)
        delta = on["latency_ms"] - off["latency_ms"]
        limit = max(30, 0.15 * off["latency_ms"])
        ok = off["ok"] and on["ok"] and delta <= limit
        qualified += int(ok)
        if on.get("doc_ids") == [item["doc_id"]]:
            hits += 1
        if not ok:
            fails.append((index, round(off["latency_ms"], 1), round(delta, 1), round(limit, 1), round((on.get("llama_ms") or 0) - (off.get("llama_ms") or 0), 1)))
        if index % 10 == 9:
            print(f"PROGRESS {index + 1}/{N} {qualified}", flush=True)
    ratio = qualified / N
    print(json.dumps({"qualified": qualified, "n": N, "ratio": round(ratio, 4), "hits": hits, "fails": fails}, ensure_ascii=False), flush=True)
    return 0 if ratio >= 0.95 and hits == N else 1


if __name__ == "__main__":
    sys.exit(main())
