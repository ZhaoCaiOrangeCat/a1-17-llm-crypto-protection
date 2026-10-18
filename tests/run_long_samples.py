import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from run_m1_m11 import ensure_llama, free_service_ports
from runtime import boot

LONG_N = 8
TOOL_N = 6
LONG_TOKENS = 256
CITIES = ["北京", "上海", "广州"]
LOG = ROOT / "data" / "logs" / "long-samples.log"
RAW = ROOT / "data" / "raw" / "long-samples.jsonl"


def pair(term, prompt, tool_args, max_tokens, index):
    order_on_first = index % 2 == 1
    if order_on_first:
        on = term.infer(prompt, tool_args=tool_args, protect=True, max_tokens=max_tokens)
        off = term.infer(prompt, tool_args=tool_args, protect=False, max_tokens=max_tokens)
    else:
        off = term.infer(prompt, tool_args=tool_args, protect=False, max_tokens=max_tokens)
        on = term.infer(prompt, tool_args=tool_args, protect=True, max_tokens=max_tokens)
    return off, on, "on-off" if order_on_first else "off-on"


def main():
    print("llama", ensure_llama(), flush=True)
    free_service_ports()
    env = boot(str(ROOT), "http://127.0.0.1:18080/v1/chat/completions", "qwen3.5-9b")
    term = env["a"]
    docs = [
        json.loads(line)
        for line in (ROOT / "fixtures" / "kb-corpus.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    rows = []

    def save(kind, index, off, on, order, chars):
        delta = on["latency_ms"] - off["latency_ms"]
        limit = 0.15 * off["latency_ms"]
        item = {
            "kind": kind,
            "i": index,
            "order": order,
            "chars": chars,
            "off_ms": round(off["latency_ms"], 1),
            "on_ms": round(on["latency_ms"], 1),
            "delta_ms": round(delta, 1),
            "limit_ms": round(limit, 1),
            "ok": bool(off["ok"] and on["ok"] and (delta <= 30 or delta <= limit)),
            "off_tokens": off.get("completion_tokens"),
            "on_tokens": on.get("completion_tokens"),
            "error": off["error_code"] or on["error_code"],
        }
        rows.append(item)
        print(
            kind,
            index,
            order,
            f"off {item['off_ms']} on {item['on_ms']} d {item['delta_ms']} lim {item['limit_ms']}",
            "tok",
            item["off_tokens"],
            item["on_tokens"],
            "PASS" if item["ok"] else "FAIL",
            item["error"],
            flush=True,
        )
        return item

    long_prompt = docs[0]
    warm = (
        "请依据下面全文写一段不少于三百字的说明。\n"
        + long_prompt["title"]
        + "\n"
        + long_prompt["text"][:700]
    )
    print("warmup long", len(warm), flush=True)
    term.infer(warm, protect=False, max_tokens=LONG_TOKENS)
    term.infer(warm, protect=True, max_tokens=LONG_TOKENS)

    for index in range(LONG_N):
        doc = docs[index % len(docs)]
        prompt = "请依据下面全文写一段不少于三百字的说明。\n" + doc["title"] + "\n" + doc["text"][:700]
        off, on, order = pair(term, prompt, None, LONG_TOKENS, index)
        item = save("long", index, off, on, order, len(prompt))
        if item["error"]:
            print("STOP long error", flush=True)
            break

    calls = {"calls": [{"city": city} for city in CITIES]}
    print("warmup tools", flush=True)
    primed = term.infer("请结合三次工具结果各用一句话说明气温。", tool_args=calls, protect=True, max_tokens=64)
    if not primed["ok"] or not isinstance((primed.get("tool") or {}).get("calls"), list):
        print("STOP tool", primed["error_code"], primed.get("tool"), flush=True)
    else:
        if len(primed["tool"]["calls"]) != 3:
            print("STOP tool count", len(primed["tool"]["calls"]), flush=True)
        else:
            for index in range(TOOL_N):
                off, on, order = pair(
                    term,
                    "请结合三次工具结果，写一段不少于两百字的说明。",
                    calls,
                    LONG_TOKENS,
                    index,
                )
                item = save("multi-tool", index, off, on, order, 24)
                if item["error"]:
                    print("STOP tool error", flush=True)
                    break

    LOG.parent.mkdir(parents=True, exist_ok=True)
    RAW.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# 长提示词与多重工具调用", ""]
    for kind in ("long", "multi-tool"):
        group = [row for row in rows if row["kind"] == kind]
        if not group:
            continue
        lines.append(
            f"- {kind}: n={len(group)} off={statistics.mean(row['off_ms'] for row in group):.1f} "
            f"on={statistics.mean(row['on_ms'] for row in group):.1f} "
            f"delta={statistics.mean(row['delta_ms'] for row in group):.1f} "
            f"pass={sum(row['ok'] for row in group)}/{len(group)}"
        )
    lines.append("")
    lines.append("顺序交替。预热不计入。原 1000 对结果未改写。")
    LOG.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with RAW.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    print("\n".join(lines), flush=True)
    failed = [row for row in rows if row["error"] or not row["ok"]]
    return 1 if failed or not any(row["kind"] == "long" and row["off_ms"] >= 1000 for row in rows) else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print("ABORT", type(exc).__name__, exc, flush=True)
        raise
