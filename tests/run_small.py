import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from client import b64d, b64e
from common.crypto import self_check, unwrap_key
from common.frame import open_frame, seal
from common.httputil import get_json, post_json
from kms.store import Store
from runtime import boot

LLAMA_PORT = 18080
MODEL = "qwen3.5-9b"
MODEL_PATH = r"E:\AI\models\llm\gguf\Qwen3.5-9B-abliterated\Qwen3.5-9B-abliterated-Q6_K.gguf"
LLAMA_EXE = r"E:\qwen agent\llama-server.exe"
LLAMA_CWD = r"E:\qwen agent"
N = 5


def llama_up() -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{LLAMA_PORT}/health", timeout=2) as resp:
            return resp.status == 200
    except Exception:
        return False


def start_llama(log_path: Path):
    if llama_up():
        return "already-up"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(log_path, "w", encoding="utf-8")
    subprocess.Popen(
        [
            LLAMA_EXE,
            "-m", MODEL_PATH,
            "--alias", MODEL,
            "--host", "127.0.0.1",
            "--port", str(LLAMA_PORT),
            "-ngl", "999",
            "-fa", "on",
            "--no-mmproj",
            "--parallel", "1",
            "-c", "2048",
            "--cache-type-k", "q8_0",
            "--cache-type-v", "q8_0",
            "--temp", "0",
            "--top-k", "1",
            "--top-p", "1",
            "--reasoning-effort", "none",
            "--no-cache-prompt",
            "--slot-prompt-similarity", "0",
        ],
        cwd=LLAMA_CWD,
        stdout=handle,
        stderr=subprocess.STDOUT,
        creationflags=0x08000000,
    )
    deadline = time.time() + 180
    while time.time() < deadline:
        if llama_up():
            return "started"
        time.sleep(1)
    tail = log_path.read_text(encoding="utf-8", errors="replace")[-800:]
    raise RuntimeError("llama-server did not become ready\n" + tail)


def prompts():
    path = ROOT / "fixtures" / "kb-corpus.jsonl"
    docs = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    made = [f"根据资料，用一句话说明{doc['title']}。" for doc in docs[:N]]
    return docs, made


def record(row, sink):
    sink.append(row)
    return row


def raw_line(row):
    return {
        "req_id": row["req_id"],
        "t_start": row["t_start"],
        "t_end": row["t_end"],
        "latency_ms": row["latency_ms"],
        "mode": row["mode"],
        "tenant_id": row["tenant_id"],
        "key_ver": row["key_ver"],
        "jti": row["jti"],
        "result": row["result"],
        "error_code": row["error_code"],
        "prompt_sha256": row["prompt_sha256"],
        "prompt_sm3": row["prompt_sm3"],
    }


def submit(term, frames, req_id, key_ver, wrap):
    _, response = post_json(
        term.gateway + "/v1/infer",
        {
            "protect": True,
            "token": term.token,
            "req_id": req_id,
            "key_ver": key_ver,
            "wrap": wrap,
            "frames": frames,
        },
        timeout=180,
    )
    return response


def make_frames(term, prompt, req_id):
    dek, key_ver, wrap = term.issue_dek()
    frames = {
        "prompt": b64e(seal(dek, "prompt", term.tenant, req_id, key_ver, prompt.encode("utf-8"))),
        "query": b64e(seal(dek, "query", term.tenant, req_id, key_ver, prompt.encode("utf-8"))),
    }
    return dek, key_ver, wrap, frames


def main():
    print("crypto self-check", flush=True)
    self_check()
    log_path = ROOT / "data" / "logs" / "llama.log"
    print("llama", start_llama(log_path), flush=True)
    print("boot services", flush=True)
    env = boot(str(ROOT), f"http://127.0.0.1:{LLAMA_PORT}/v1/chat/completions", MODEL)
    docs, queries = prompts()
    raw = []
    results = []

    def mark(name, ok, detail):
        results.append((name, ok, detail))
        print(f"{'PASS' if ok else 'FAIL'} {name} {detail}", flush=True)

    term = env["a"]
    other = env["b"]
    admin = env["admin"]
    prompt0 = f"根据资料，用一句话说明{docs[0]['title']}。北京当前气温是多少？"
    row = term.infer(prompt0, tool_args={"city": "北京"}, protect=True)
    record(row, raw)
    tool = row.get("tool") or {}
    temp_ok = isinstance(tool.get("temperature_2m"), (int, float))
    mark(
        "E1 链路",
        row["ok"] and temp_ok and tool.get("provider") == "Open-Meteo" and row["upstream_leaked"] is False and bool(row["doc_ids"]),
        f"result={row['result']} temp={tool.get('temperature_2m')} place={tool.get('place')} docs={row['doc_ids']} leaked={row['upstream_leaked']} out={row['content'][:40]!r}",
    )
    _, scan = post_json(env["gateway"] + "/v1/scan", {"needle": docs[0]["title"]})
    kb_bytes = (ROOT / "var" / "kb" / "tenant-a.jsonl").read_bytes()
    tool_bytes = (ROOT / "var" / "tool" / "config.bin").read_bytes()
    title_b = docs[0]["title"].encode("utf-8")
    host_b = b"api.open-meteo.com"
    mark(
        "E1 密文边界",
        scan.get("found") is False and title_b not in kb_bytes and host_b not in tool_bytes and not list((ROOT / "var" / "tmp").glob("*")),
        f"forward_hit={scan.get('found')} kb_bytes={len(kb_bytes)}",
    )

    print("warmup", flush=True)
    term.infer(queries[0], protect=False)
    term.infer(queries[0], protect=True)

    ok_n = 0
    for text in queries:
        item = term.infer(text, protect=True)
        record(item, raw)
        ok_n += int(item["ok"])
    mark("E2 连续保护", ok_n == N, f"{ok_n}/{N}")

    qualified = 0
    deltas = []
    latency_n = 20
    latency_prompt = queries[0]
    for _ in range(latency_n):
        off = term.infer(latency_prompt, protect=False)
        on = term.infer(latency_prompt, protect=True)
        record(off, raw)
        record(on, raw)
        delta = on["latency_ms"] - off["latency_ms"]
        deltas.append(round(delta, 1))
        limit = 0.15 * off["latency_ms"]
        if off["ok"] and on["ok"] and (delta <= limit or delta <= 30):
            qualified += 1
    mark(
        "E3 时延",
        latency_n > 0 and qualified / latency_n >= 0.95,
        f"{qualified}/{latency_n} delta_ms={deltas}",
    )

    identified = 0
    expected = 2
    base_prompt = queries[0]
    dek, key_ver, wrap, frames = make_frames(term, base_prompt, "tamper-ct")
    blob = bytearray(b64d(frames["prompt"]))
    blob[-40] ^= 0x01
    frames["prompt"] = b64e(bytes(blob))
    tamper_ct = submit(term, frames, "tamper-ct", key_ver, wrap)
    if tamper_ct.get("error") == "TAG_FAIL":
        identified += 1
    dek, key_ver, wrap, frames = make_frames(term, base_prompt, "tamper-mac")
    blob = bytearray(b64d(frames["prompt"]))
    blob[-1] ^= 0x01
    frames["prompt"] = b64e(bytes(blob))
    tamper_mac = submit(term, frames, "tamper-mac", key_ver, wrap)
    if tamper_mac.get("error") == "TAG_FAIL":
        identified += 1
    _, found = post_json(env["audit"] + "/v1/find", {"result": "TAG_FAIL"})
    mark(
        "E4 篡改",
        identified == expected and found.get("n", 0) >= expected,
        f"identified={identified}/{expected} audit={found.get('n')} ct={tamper_ct.get('error')} mac={tamper_mac.get('error')}",
    )

    dek, key_ver, wrap, frames = make_frames(term, base_prompt, "replay-1")
    first = submit(term, frames, "replay-1", key_ver, wrap)
    second = submit(term, frames, "replay-1", key_ver, wrap)
    dek, key_ver, wrap, frames = make_frames(term, base_prompt, "window-1")
    blob = bytearray(b64d(frames["prompt"]))
    blob[10:18] = b"\x00" * 8
    frames["prompt"] = b64e(bytes(blob))
    window = submit(term, frames, "window-1", key_ver, wrap)
    _, replay_hits = post_json(env["audit"] + "/v1/find", {"req_id": "replay-1", "result": "REPLAY"})
    mark(
        "E5 重放",
        first.get("ok") is True and second.get("error") == "REPLAY" and window.get("error") == "WINDOW" and replay_hits.get("n", 0) >= 1,
        f"first={first.get('error') or 'OK'} second={second.get('error')} window={window.get('error')}",
    )

    admin.ensure()
    rotated = 0
    for _ in range(5):
        _, response = post_json(env["kms"] + "/v1/rotate", {"token": admin.token, "tenant_id": "tenant-a"})
        if response.get("ok") and response.get("state_ok"):
            rotated += 1
    _, status = post_json(env["kms"] + "/v1/status", {"token": admin.token, "tenant_id": "tenant-a"})
    alive = []

    def rotate_more():
        for _ in range(3):
            post_json(env["kms"] + "/v1/rotate", {"token": admin.token, "tenant_id": "tenant-a"})

    def infer_more():
        for text in queries[:3]:
            alive.append(term.infer(text, protect=True)["ok"])

    import threading
    left = threading.Thread(target=rotate_more)
    right = threading.Thread(target=infer_more)
    left.start()
    right.start()
    left.join()
    right.join()
    inflight_ok = sum(1 for item in alive if item)
    mark(
        "E6 换钥",
        rotated == 5 and status.get("active_count") == 1 and inflight_ok == len(alive) and len(alive) == 3,
        f"rotate={rotated}/5 active={status.get('active_count')} inflight={inflight_ok}/{len(alive)}",
    )

    admin.ensure()
    term.login()
    jti = term.token["claims"]["jti"]
    _, revoked = post_json(env["kms"] + "/v1/revoke", {"token": admin.token, "jti": jti})
    t0 = revoked.get("t0")
    denied = 0
    sent = 0
    for _ in range(3):
        sent += 1
        item = term.infer(queries[0], protect=True)
        if item["error_code"] == "AUTH_REVOKED" and time.time() - t0 <= 60:
            denied += 1
    mark("E7 吊销", denied == sent and revoked.get("ok") is True, f"denied={denied}/{sent} t0={t0}")

    term.login()
    _, key_a = post_json(env["sidecar"] + "/v1/cache-key", {"token": term.token, "prompt": queries[0]})
    other.ensure()
    _, key_b = post_json(env["sidecar"] + "/v1/cache-key", {"token": env["b"].token, "prompt": queries[0]})
    _, crossed = post_json(env["kb"] + "/v1/cross-open", {"token": env["b"].token, "victim": "tenant-a"})
    dek, key_ver, wrap, frames = make_frames(term, queries[0], "cross-1")
    _, crossed_req = post_json(
        env["gateway"] + "/v1/infer",
        {
            "protect": True,
            "token": other.token,
            "req_id": "cross-1",
            "key_ver": key_ver,
            "wrap": wrap,
            "frames": frames,
        },
        timeout=30,
    )
    archive = ROOT / "var" / "archive" / "kv-last.bin"
    archive_hit = archive.exists() and title_b in archive.read_bytes()
    mark(
        "E8 隔离",
        key_a.get("ok") and key_b.get("ok") and key_a["cache_key"] != key_b["cache_key"] and crossed.get("opened") is False and crossed_req.get("error") == "AUTHZ_DENY" and not archive_hit,
        f"cache_differ={key_a.get('cache_key') != key_b.get('cache_key')} cross={crossed.get('error')} deny={crossed_req.get('error')}",
    )

    admin.ensure()
    reopened = Store(env["store_path"])
    state = reopened.status("tenant-a")
    _, key_revoke = post_json(
        env["kms"] + "/v1/kek/revoke",
        {"token": admin.token, "tenant_id": "tenant-a", "version": 1},
    )
    _, recover = post_json(
        env["kms"] + "/v1/kek/recover",
        {"token": admin.token, "tenant_id": "tenant-a", "version": 1},
    )
    mark(
        "E9 状态",
        state["active_count"] == 1 and key_revoke.get("ok") is True and recover.get("result") == "REVOKED_DENIED",
        f"active={state['active_count']} revoke={key_revoke.get('ok')} recover={recover.get('result')}",
    )

    verified = get_json(env["audit"] + "/v1/verify")
    mark("审计链", verified.get("ok") is True and verified.get("count", 0) > 0, f"count={verified.get('count')}")

    out_dir = ROOT / "data" / "raw"
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "small.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
        for row in raw:
            handle.write(json.dumps(raw_line(row), ensure_ascii=False) + "\n")
    report = ROOT / "data" / "reports"
    report.mkdir(parents=True, exist_ok=True)
    lines = ["# 小规模实验记录", "", f"模型: {MODEL_PATH}", f"样本: {N}", ""]
    for name, ok, detail in results:
        lines.append(f"- {'PASS' if ok else 'FAIL'} {name}: {detail}")
    lines.append("")
    lines.append("全量 1000 次未执行。")
    (report / "small.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    failed = [name for name, ok, _ in results if not ok]
    print("FAILED" if failed else "ALL PASS", failed, flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print("ABORT", exc, flush=True)
        raise
