import json
import time
import urllib.request

URL = "http://127.0.0.1:18080/v1/chat/completions"


def once(label, user):
    payload = {
        "model": "qwen3.5-9b",
        "messages": [
            {"role": "system", "content": "只依据给定资料和工具结果。用五句话回答，每句不少于三十字。不要输出思维过程。"},
            {"role": "user", "content": user},
        ],
        "max_tokens": 200,
        "temperature": 0,
        "chat_template_kwargs": {"enable_thinking": False},
        "enable_thinking": False,
    }
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(URL, data=raw, headers={"Content-Type": "application/json"})
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=180) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    ms = (time.perf_counter() - t0) * 1000
    usage = body.get("usage") or {}
    print(label, round(ms, 1), "prompt", usage.get("prompt_tokens"), "completion", usage.get("completion_tokens"), flush=True)


text = "请用五句话说明泡泡战士，每句不少于三十字。\n\n资料:\n[cmrc-0001] 泡泡战士：基于《跑跑卡丁车》与《泡泡堂》上所开发的游戏，由韩国Nexon开发与发行。中国大陆由盛大游戏运营。\n工具结果：{\"place\":\"北京\",\"temperature_2m\":14.4,\"provider\":\"Open-Meteo\"}"
for i in range(8):
    once(i, text)
