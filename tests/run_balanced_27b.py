import json
import statistics
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from run_m1_m11 import LLAMA_CWD, LLAMA_EXE, LLAMA_PORT, free_service_ports, image_name, listeners, load_prompts, prefer_llama
from runtime import boot

MODEL = "qwen3.8-27b"
MODEL_PATH = r"E:\AI\models\llm\gguf\Qwen3.8-27B\Qwen3.8-27B-UD-Q5_K_XL.gguf"
N = 1000
WARM = 10
LOG = ROOT / "data" / "logs" / "balanced-27b-1000.log"
RAW = ROOT / "data" / "raw" / "m5-balanced-27b-1000.jsonl"


def start_27b():
    for pid in listeners(LLAMA_PORT):
        if image_name(pid).lower().startswith("llama-server"):
            subprocess.run(["taskkill", "/PID", str(pid), "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(2)
    log_path = ROOT / "data" / "logs" / "llama-27b.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(log_path, "w", encoding="utf-8")
    args = [
        LLAMA_EXE, "-m", MODEL_PATH, "--alias", MODEL,
        "--host", "127.0.0.1", "--port", str(LLAMA_PORT),
        "-ngl", "999", "-fa", "on", "--no-mmproj", "--parallel", "1",
        "-c", "2048", "--cache-type-k", "q8_0", "--cache-type-v", "q8_0",
        "--temp", "0", "--top-k", "1", "--top-p", "1",
        "--reasoning-effort", "none", "--no-cache-prompt", "--slot-prompt-similarity", "0",
    ]
    subprocess.Popen(args, cwd=LLAMA_CWD, stdout=handle, stderr=subprocess.STDOUT, creationflags=0x08000000)
    deadline = time.time() + 300
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{LLAMA_PORT}/health", timeout=2) as resp:
                if resp.status == 200:
                    pids = listeners(LLAMA_PORT)
                    if pids:
                        prefer_llama(pids[0])
                    return "started"
        except Exception:
            time.sleep(2)
    tail = log_path.read_text(encoding="utf-8", errors="replace")[-600:]
    raise RuntimeError("27B did not become ready\n" + tail)


def both_orders(term, prompt):
    off_a = term.infer(prompt, tool_args={"city": "北京"}, protect=False)
    on_a = term.infer(prompt, tool_args={"city": "北京"}, protect=True)
    on_b = term.infer(prompt, tool_args={"city": "北京"}, protect=True)
    off_b = term.infer(prompt, tool_args={"city": "北京"}, protect=False)
    return off_a, on_a, on_b, off_b


def main():
    print("llama", start_27b(), MODEL_PATH, flush=True)
    free_service_ports()
    env = boot(str(ROOT), f"http://127.0.0.1:{LLAMA_PORT}/v1/chat/completions", MODEL)
    term = env["a"]
    prompts = load_prompts()
    warm_off = []
    for item in prompts[:WARM]:
        off_a, on_a, on_b, off_b = both_orders(term, item["prompt"])
        if any(not call["ok"] for call in (off_a, on_a, on_b, off_b)):
            print("STOP warmup", [call["error_code"] for call in (off_a, on_a, on_b, off_b)], flush=True)
            return 1
        warm_off.extend([off_a["latency_ms"], off_b["latency_ms"]])
    baseline = statistics.median(warm_off)
    print(f"baseline_off {baseline:.1f}", flush=True)
    rows = []
    busy = 0
    for index, item in enumerate(prompts[:N]):
        calls = both_orders(term, item["prompt"])
        if any(not call["ok"] for call in calls):
            print("STOP error", index, [call["error_code"] for call in calls], flush=True)
            break
        off_a, on_a, on_b, off_b = calls
        slow = max(call["latency_ms"] for call in calls)
        if slow > baseline * 2.5:
            busy += 1
            print(f"STALL {index} {slow:.0f}", flush=True)
            if busy >= 3:
                print("STOP machine busy", flush=True)
                break
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
            }
        )
        if len(rows) % 25 == 0:
            passed_now = sum(row["ok"] for row in rows)
            print(
                f"PROGRESS {len(rows)}/{N} pass {passed_now} "
                f"delta {statistics.mean(row['delta'] for row in rows):.1f}",
                flush=True,
            )
            RAW.parent.mkdir(parents=True, exist_ok=True)
            with RAW.open("w", encoding="utf-8", newline="\n") as handle:
                for saved in rows:
                    handle.write(json.dumps(saved, ensure_ascii=False) + "\n")
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
            "# 27B 两种顺序抵消",
            "",
            f"模型: {MODEL_PATH}",
            f"样本: {len(rows)}",
            f"不加保护平均: {statistics.mean(row['t_off'] for row in rows):.1f} ms",
            f"加保护平均: {statistics.mean(row['t_on'] for row in rows):.1f} ms",
            f"先关后开平均差: {statistics.mean(row['delta_off_on'] for row in rows):.1f} ms",
            f"先开后关平均差: {statistics.mean(row['delta_on_off'] for row in rows):.1f} ms",
            f"抵消后平均附加时延: {statistics.mean(row['delta'] for row in rows):.1f} ms",
            f"合格: {passed}/{len(rows)}",
            "",
            "9B 的 1000 对未改写。18080 现在是 27B。",
        ]
    )
    LOG.write_text(text + "\n", encoding="utf-8")
    run_dir = ROOT / "data" / "runs" / ("27b-balanced-" + time.strftime("%Y%m%d-%H%M%S"))
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "balanced-27b-1000.log").write_text(text + "\n", encoding="utf-8")
    (run_dir / "m5-balanced-27b-1000.jsonl").write_text(RAW.read_text(encoding="utf-8"), encoding="utf-8")
    print(text, flush=True)
    print("RUN_DIR", run_dir, flush=True)
    done = len(rows) == N and passed / len(rows) >= 0.95
    print("ALL PASS" if done else "FAILED", flush=True)
    return 0 if done else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print("ABORT", type(exc).__name__, exc, flush=True)
        raise
