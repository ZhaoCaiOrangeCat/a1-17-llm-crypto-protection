import sys
from pathlib import Path

ROOT = Path(r"C:\Users\zhaoc\Desktop\密码")
sys.path.insert(0, str(ROOT / "src"))
from runtime import boot
from common.httputil import post_json

env = boot(str(ROOT), "http://127.0.0.1:18080/v1/chat/completions", "qwen3.5-9b")
term = env["a"]
prompt = "根据资料，用一句话说明泡泡战士。"
for i in range(4):
    off = term.infer(prompt, protect=False)
    on = term.infer(prompt, protect=True)
    print(
        i,
        "off", round(off["latency_ms"], 1), off.get("llama_ms"),
        "on", round(on["latency_ms"], 1), on.get("llama_ms"),
        "d", round(on["latency_ms"] - off["latency_ms"], 1),
        "dl", None if off.get("llama_ms") is None else round(on["llama_ms"] - off["llama_ms"], 1),
        "kb", on.get("kb_ms"),
        "sc", on.get("sc_ms"),
        "unwrap", on.get("unwrap_ms"),
        "open", on.get("open_ms"),
        on.get("phase"),
    )
