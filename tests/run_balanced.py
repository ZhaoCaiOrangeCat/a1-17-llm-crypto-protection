import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from run_m1_m11 import ensure_llama, free_service_ports, load_prompts
from runtime import boot

LOG = ROOT / "data" / "logs" / "balanced.log"
RAW = ROOT / "data" / "raw" / "m5-balanced.jsonl"
N = 1000
WARM = 10


def both_orders(term, prompt):
    off_a = term.infer(prompt, tool_args={"city": "北京"}, protect=False)
    on_a = term.infer(prompt, tool_args={"city": "北京"}, protect=True)
    on_b = term.infer(prompt, tool_args={"city": "北京"}, protect=True)
    off_b = term.infer(prompt, tool_args={"city": "北京"}, protect=False)
    return off_a, on_a, on_b, off_b


def main():
    print("llama", ensure_llama(), flush=True)
    free_service_ports()
    env = boot(str(ROOT), "http://127.0.0.1:18080/v1/chat/completions", "qwen3.5-9b")
    term = env["a"]
    prompts = load_prompts()
    warm_off = []
    for item in prompts[:WARM]:
        off_a, on_a, on_b, off_b = both_orders(term, item["prompt"])
        warm_off.extend([off_a["latency_ms"], off_b["latency_ms"]])
    baseline = statistics.median(warm_off)
    print(f"baseline_off {baseline:.1f}", flush=True)
    rows = []
    busy = 0
    for index, item in enumerate(prompts[:N]):
        off_a, on_a, on_b, off_b = both_orders(term, item["prompt"])
        calls = (off_a, on_a, on_b, off_b)
        if any(not call["ok"] for call in calls):
            print("STOP error", index, [call["error_code"] for call in calls], flush=True)
            break
        slow = max(call["latency_ms"] for call in calls)
        if slow > baseline * 1.5:
            busy += 1
            print(f"STALL {index} {slow:.0f}", flush=True)
            if busy >= 5:
                print("STOP machine busy", flush=True)
                break
            time.sleep(2)
            continue
        busy = 0
        d_a = on_a["latency_ms"] - off_a["latency_ms"]
        d_b = on_b["latency_ms"] - off_b["latency_ms"]
        delta = (d_a + d_b) / 2
        t_off = (off_a["latency_ms"] + off_b["latency_ms"]) / 2
        t_on = (on_a["latency_ms"] + on_b["latency_ms"]) / 2
        ok = delta <= 30 or delta <= 0.15 * t_off
        rows.append(
            {
                "i": index,
                "t_off": round(t_off, 1),
                "t_on": round(t_on, 1),
                "delta_off_on": round(d_a, 1),
                "delta_on_off": round(d_b, 1),
                "delta": round(delta, 1),
                "ok": ok,
                "audit_hash": on_a.get("audit_hash") or on_b.get("audit_hash") or "",
            }
        )
        if len(rows) % 25 == 0:
            passed = sum(row["ok"] for row in rows)
            print(
                f"PROGRESS {len(rows)}/{N} pass {passed} "
                f"delta {statistics.mean(row['delta'] for row in rows):.1f}",
                flush=True,
            )
        if len(rows) == 40 and sum(row["ok"] for row in rows) < 36:
            print("STOP balanced gate", flush=True)
            break
    LOG.parent.mkdir(parents=True, exist_ok=True)
    RAW.parent.mkdir(parents=True, exist_ok=True)
    with RAW.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    if not rows:
        print("FAILED []", flush=True)
        return 1
    passed = sum(row["ok"] for row in rows)
    text = "\n".join(
        [
            "# 两种顺序抵消后的附加时延",
            "",
            f"样本: {len(rows)}",
            f"不加保护平均: {statistics.mean(row['t_off'] for row in rows):.1f} ms",
            f"加保护平均: {statistics.mean(row['t_on'] for row in rows):.1f} ms",
            f"先关后开平均差: {statistics.mean(row['delta_off_on'] for row in rows):.1f} ms",
            f"先开后关平均差: {statistics.mean(row['delta_on_off'] for row in rows):.1f} ms",
            f"抵消后平均附加时延: {statistics.mean(row['delta'] for row in rows):.1f} ms",
            f"合格: {passed}/{len(rows)}",
            "",
            "每条提示词测两种顺序。附加时延是两次差值的平均。预热不计入。",
        ]
    )
    LOG.write_text(text + "\n", encoding="utf-8")
    print(text, flush=True)
    print("ALL PASS" if passed / len(rows) >= 0.95 else "FAILED", flush=True)
    return 0 if len(rows) == N and passed / len(rows) >= 0.95 else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print("ABORT", type(exc).__name__, exc, flush=True)
        raise
