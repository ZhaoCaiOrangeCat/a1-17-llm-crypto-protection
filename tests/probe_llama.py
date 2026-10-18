import json
import time
import urllib.request

URL = "http://127.0.0.1:18080/v1/chat/completions"


def once(extra):
    payload = {
        "model": "qwen3.5-9b",
        "messages": [
            {"role": "system", "content": "用不超过40个汉字回答。"},
            {"role": "user", "content": "根据资料，用一句话说明泡泡战士。资料：泡泡战士是一款游戏。"},
        ],
        "temperature": 0,
        "chat_template_kwargs": {"enable_thinking": False},
        "enable_thinking": False,
    }
    payload.update(extra)
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(URL, data=raw, headers={"Content-Type": "application/json; charset=utf-8"})
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=180) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    ms = (time.perf_counter() - t0) * 1000
    msg = body["choices"][0]["message"]
    content = msg.get("content") or ""
    print(extra, "ms", round(ms, 1), "chars", len(content), "usage", body.get("usage"), "finish", body["choices"][0].get("finish_reason"))


once({"max_tokens": 32})
once({"max_tokens": 32, "ignore_eos": True})
once({"max_tokens": 64, "ignore_eos": True})
