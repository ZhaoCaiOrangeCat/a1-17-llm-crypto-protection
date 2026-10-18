import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
from run_m1_m11 import ensure_llama, free_service_ports
from sidecar.server import llama_complete
from runtime import boot

def main():
    print("llama", ensure_llama(), flush=True)
    free_service_ports()
    env = boot(str(ROOT), "http://127.0.0.1:18080/v1/chat/completions", "qwen3.5-9b")
    term = env["a"]
    prompt = "请用五句话说明泡泡战士，每句不少于三十字。"
    args = {"city": "北京"}
    term.infer(prompt, tool_args=args, protect=False)
    term.infer(prompt, tool_args=args, protect=True)
    for i in range(8):
        off = term.infer(prompt, tool_args=args, protect=False)
        on = term.infer(prompt, tool_args=args, protect=True)
        print(
            i,
            "off", round(off["latency_ms"], 1), off.get("llama_ms"),
            "on", round(on["latency_ms"], 1), on.get("llama_ms"),
            "d", round(on["latency_ms"] - off["latency_ms"], 1),
            "dl", None if off.get("llama_ms") is None else round(on["llama_ms"] - off["llama_ms"], 1),
            "kb", on.get("kb_ms"),
            "sc", on.get("sc_ms"),
            "phase", on.get("phase"),
            "docs", on.get("doc_ids"),
            "usage", getattr(llama_complete, "last_usage", None),
            flush=True,
        )

if __name__ == "__main__":
    main()
