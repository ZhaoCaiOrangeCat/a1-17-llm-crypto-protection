import json
import os
import shutil
import sqlite3
import statistics
import subprocess
import sys
import threading
import time
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from client import Terminal, b64d, b64e
from common.crypto import CryptoError, self_check, sm2_verify, sm3_digest
from common.frame import canon, open_frame, seal
from common.httputil import post_json
from kms.store import Store
from runtime import boot
from sidecar.server import LLAMA_MAX_TOKENS

LLAMA_PORT = 18080
MODEL = "qwen3.5-9b"
MODEL_PATH = r"E:\AI\models\llm\gguf\Qwen3.5-9B-abliterated\Qwen3.5-9B-abliterated-Q6_K.gguf"
LLAMA_EXE = r"E:\qwen agent\llama-server.exe"
LLAMA_CWD = r"E:\qwen agent"
LLAMA_ARGS = [
    LLAMA_EXE, "-m", MODEL_PATH, "--alias", MODEL,
    "--host", "127.0.0.1", "--port", str(LLAMA_PORT),
    "-ngl", "999", "-fa", "on", "--no-mmproj", "--parallel", "1",
    "-c", "2048", "--cache-type-k", "q8_0", "--cache-type-v", "q8_0",
    "--temp", "0", "--top-k", "1", "--top-p", "1",
    "--threads", "8", "--prio", "2", "--load-mode", "mlock", "-lv", "0",
    "--reasoning-effort", "none", "--cache-ram", "2048",
    "--no-cache-idle-slots", "--slot-prompt-similarity", "0.5",
    "--slot-save-path", r"C:\Users\zhaoc\Desktop\a117-slots",
]
CITIES = ["北京", "上海", "广州", "深圳", "成都", "杭州", "西安", "武汉", "南京", "青岛"]


def listeners(port):
    out = subprocess.check_output(["netstat", "-ano"], text=True, errors="replace")
    found = []
    for line in out.splitlines():
        if "LISTENING" not in line:
            continue
        parts = line.split()
        if len(parts) < 5:
            continue
        if parts[1].endswith(":" + str(port)):
            found.append(int(parts[-1]))
    return found


def image_name(pid):
    out = subprocess.check_output(
        ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
        text=True,
        errors="replace",
    )
    if out.startswith('"'):
        return out.split('"', 2)[1]
    return ""


def free_service_ports():
    for port in (8711, 8712, 8713, 8714, 8715, 8716):
        for pid in listeners(port):
            if image_name(pid).lower().startswith("python"):
                subprocess.run(["taskkill", "/PID", str(pid), "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def prefer_llama(pid: int):
    import ctypes
    kernel = ctypes.windll.kernel32
    handle = kernel.OpenProcess(0x0200 | 0x0400, False, int(pid))
    if not handle:
        return
    kernel.SetPriorityClass(handle, 0x00000080)
    kernel.CloseHandle(handle)


def llama_up():
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{LLAMA_PORT}/health", timeout=2) as resp:
            return resp.status == 200
    except Exception:
        return False


def ensure_llama():
    stamp_path = ROOT / "data" / "logs" / "llama.cmdline"
    running = listeners(LLAMA_PORT)
    stamp = {}
    if stamp_path.exists():
        stamp = json.loads(stamp_path.read_text(encoding="utf-8"))
    if running and stamp.get("pid") in running and stamp.get("args") == LLAMA_ARGS[1:]:
        prefer_llama(stamp["pid"])
        return "already-up"
    for pid in running:
        if image_name(pid).lower().startswith("llama-server"):
            subprocess.run(["taskkill", "/PID", str(pid), "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1)
    stamp_path.parent.mkdir(parents=True, exist_ok=True)
    Path(r"C:\Users\zhaoc\Desktop\a117-slots").mkdir(parents=True, exist_ok=True)
    log_path = ROOT / "data" / "logs" / "llama.log"
    handle = open(log_path, "w", encoding="utf-8")
    subprocess.Popen(LLAMA_ARGS, cwd=LLAMA_CWD, stdout=handle, stderr=subprocess.STDOUT, creationflags=0x08000000)
    deadline = time.time() + 180
    while time.time() < deadline:
        if llama_up():
            pids = listeners(LLAMA_PORT)
            stamp_path.write_text(
                json.dumps({"pid": pids[0] if pids else 0, "args": LLAMA_ARGS[1:]}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            if pids:
                prefer_llama(pids[0])
            return "started"
        time.sleep(1)
    tail = log_path.read_text(encoding="utf-8", errors="replace")[-500:]
    raise RuntimeError("llama-server did not become ready\n" + tail)


def load_prompts():
    path = ROOT / "fixtures" / "prompts-1000.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(rows) != 1000:
        raise RuntimeError(f"prompts {len(rows)}")
    return rows


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
        "audit_hash": row.get("audit_hash") or "",
    }


def protected_ok(row):
    return bool(row["ok"]) and row["result"] == "OK" and bool(row.get("audit_hash"))


def submit(term, frames, req_id, key_ver, wrap, spill=False):
    _, response = post_json(
        term.gateway + "/v1/infer",
        {
            "protect": True,
            "token": term.token,
            "req_id": req_id,
            "key_ver": key_ver,
            "wrap": wrap,
            "frames": frames,
            "spill": spill,
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


def span_after(blob, start):
    tlen = int.from_bytes(blob[start:start + 2], "big")
    tenant = (start + 2, start + 2 + tlen)
    off = tenant[1]
    rlen = int.from_bytes(blob[off:off + 2], "big")
    req = (off + 2, off + 2 + rlen)
    nonce = (req[1], req[1] + 16)
    clen_at = nonce[1]
    clen = int.from_bytes(blob[clen_at:clen_at + 4], "big")
    ct = (clen_at + 4, clen_at + 4 + clen)
    return tenant, nonce, ct


def audit_hit(env, token, req_id, result):
    _, found = post_json(
        env["audit"] + "/v1/find",
        {"token": token, "req_id": req_id, "result": result},
    )
    return found.get("n", 0) >= 1


def gpu_line():
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader"],
            text=True,
            errors="replace",
        )
        return out.strip()
    except Exception as exc:
        return str(exc)


def verify_chain(env):
    pub = env["kms_pub"]
    prev = b"\x00" * 32
    count = 0
    checkpoints = 0
    hashes = set()
    with open(env["audit_path"], "r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            count += 1
            digest = sm3_digest(prev + canon(row["record"]))
            if digest.hex() != row["hash"] or row["n"] != count:
                return False, count, checkpoints, hashes
            if count % 100 == 0:
                if not row.get("checkpoint") or not sm2_verify(pub, digest, row["checkpoint"]):
                    return False, count, checkpoints, hashes
                checkpoints += 1
            prev = digest
            hashes.add(row["hash"])
    return True, count, checkpoints, hashes


def preserve_previous():
    dest = ROOT / "data" / "runs" / "2026-10-16-full"
    dest.mkdir(parents=True, exist_ok=True)
    mapping = [
        (ROOT / "data" / "reports" / "summary.md", dest / "summary.md"),
        (ROOT / "data" / "reports" / "env.md", dest / "env.md"),
        (ROOT / "data" / "audit" / "chain.jsonl", dest / "chain.jsonl"),
        (ROOT / "data" / "logs" / "m1-m11-latest.log", dest / "run.log"),
        (ROOT / "data" / "raw" / "m1.jsonl", dest / "m1.jsonl"),
        (ROOT / "data" / "raw" / "m5.jsonl", dest / "m5.jsonl"),
        (ROOT / "data" / "raw" / "m7.jsonl", dest / "m7.jsonl"),
        (ROOT / "data" / "raw" / "m11.jsonl", dest / "m11.jsonl"),
    ]
    for src, target in mapping:
        if src.exists() and not target.exists():
            shutil.copy2(src, target)


def main():
    preserve_previous()
    run_dir = ROOT / "data" / "runs" / time.strftime("%Y%m%d-%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)
    log_path = ROOT / "data" / "logs" / "m1-m11-latest.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_fp = open(log_path, "w", encoding="utf-8", newline="\n")
    run_fp = open(run_dir / "run.log", "w", encoding="utf-8", newline="\n")

    class Tee:
        def __init__(self, *files):
            self.files = files

        def write(self, data):
            for item in self.files:
                item.write(data)
                item.flush()

        def flush(self):
            for item in self.files:
                item.flush()

    sys.stdout = Tee(sys.__stdout__, log_fp, run_fp)
    sys.stderr = Tee(sys.__stderr__, log_fp, run_fp)
    phase = sys.argv[1] if len(sys.argv) > 1 else "full"
    full = phase == "full"
    n_pair = 1000 if full else 30
    n_rot = 100 if full else 5
    n_win = 200 if full else 12
    n_tool = 10 if full else 1
    warmup = 20 if full else 4
    if LLAMA_MAX_TOKENS < 32:
        raise RuntimeError("max_tokens")
    print("crypto self-check", flush=True)
    self_check()
    print("llama", ensure_llama(), flush=True)
    free_service_ports()
    print("boot", flush=True)
    env = boot(str(ROOT), f"http://127.0.0.1:{LLAMA_PORT}/v1/chat/completions", MODEL)
    prompts = load_prompts()
    term = env["a"]
    other = env["b"]
    admin = env["admin"]
    gates = []

    def mark(name, ok, detail):
        gates.append((name, bool(ok), detail))
        print(f"{'PASS' if ok else 'FAIL'} {name} {detail}", flush=True)

    saved = term.issue_dek()
    saved_ver, saved_wrap = saved[1], b64d(saved[2])
    title = "泡泡战士"
    prompt0 = f"根据资料，用一句话说明{title}。北京当前气温是多少？"
    row = term.infer(prompt0, tool_args={"city": "北京"}, protect=True)
    tool = row.get("tool") or {}
    mark(
        "E1 链路",
        protected_ok(row)
        and isinstance(tool.get("temperature_2m"), (int, float))
        and tool.get("provider") == "Open-Meteo"
        and row["upstream_leaked"] is False
        and row["doc_ids"] == ["cmrc-0001"],
        f"temp={tool.get('temperature_2m')} docs={row['doc_ids']} leaked={row['upstream_leaked']} err={row['error_code']}",
    )
    _, scan = post_json(env["gateway"] + "/v1/scan", {"needle": title})
    kb_bytes = (ROOT / "var" / "kb" / "tenant-a.jsonl").read_bytes()
    corpus = (ROOT / "fixtures" / "kb-corpus.jsonl").read_bytes()
    tool_bytes = (ROOT / "var" / "tool" / "config.bin").read_bytes()
    spec_bytes = (ROOT / "fixtures" / "tools" / "open-meteo-forecast.yml").read_bytes()
    title_b = title.encode("utf-8")
    mark(
        "E1 密文边界",
        scan.get("found") is False
        and title_b not in kb_bytes
        and title_b in corpus
        and b"api.open-meteo.com" not in tool_bytes
        and b"https://api.open-meteo.com" in spec_bytes
        and not list((ROOT / "var" / "tmp").glob("*")),
        f"forward_hit={scan.get('found')} kb_bytes={len(kb_bytes)}",
    )
    secret = env["tool_obj"].secret.encode("utf-8")
    wire = env["side_obj"].last_wire or b""
    llama_raw = env["side_obj"].last_llama or b""
    backup = (ROOT / "var" / "backup" / "tenant-a.jsonl").read_bytes()
    backup_line = json.loads((ROOT / "var" / "backup" / "tenant-a.jsonl").read_text(encoding="utf-8").splitlines()[1])
    backup_blob = b64d(backup_line["frame"])
    backup_open = False
    backup_wrong = False
    try:
        opened = open_frame(env["kb_obj"].keys["tenant-a"]["dek"], backup_blob)
        backup_open = b"doc_id" in opened[1]
    except CryptoError:
        backup_open = False
    try:
        open_frame(env["kb_obj"].keys["tenant-b"]["dek"], backup_blob)
    except CryptoError as exc:
        backup_wrong = exc.code == "TAG_FAIL"
    _, denied_rotate = post_json(env["kms"] + "/v1/rotate", {"token": term.token, "tenant_id": "tenant-a"})
    denied_infer = admin.infer(prompts[0]["prompt"], protect=True)
    _, denied_audit = post_json(
        env["audit"] + "/v1/find",
        {"token": term.token, "tenant_id": "tenant-b", "result": "OK"},
    )
    mark(
        "细粒度授权",
        denied_rotate.get("error") == "AUTHZ_DENY"
        and denied_infer["error_code"] == "AUTHZ_DENY"
        and denied_audit.get("error") == "AUTHZ_DENY",
        f"rotate={denied_rotate.get('error')} infer={denied_infer['error_code']} audit={denied_audit.get('error')}",
    )
    mark(
        "窃听与备份",
        title_b not in wire
        and secret not in wire
        and secret not in llama_raw
        and secret not in tool_bytes
        and b"api.open-meteo.com" not in wire
        and title_b not in backup
        and backup_open
        and backup_wrong,
        f"wire={len(wire)} backup_open={backup_open} backup_wrong={backup_wrong}",
    )
    tool_ok = 1 if protected_ok(row) else 0
    for city in CITIES[: n_tool - 1]:
        item = term.infer(f"请查询{city}当前气温。", tool_args={"city": city}, protect=True)
        weather = item.get("tool") or {}
        if protected_ok(item) and isinstance(weather.get("temperature_2m"), (int, float)):
            tool_ok += 1
        else:
            print("TOOL", city, item["error_code"], weather, flush=True)
    mark("工具实呼", tool_ok == n_tool, f"{tool_ok}/{n_tool}")

    identified = 0
    expected_attacks = 0
    base = prompts[0]["prompt"]

    def tamper(req_id, mutate, code):
        nonlocal identified, expected_attacks
        expected_attacks += 1
        _, key_ver, wrap, frames = make_frames(term, base, req_id)
        blob = bytearray(b64d(frames["prompt"]))
        mutate(blob)
        frames["prompt"] = b64e(bytes(blob))
        response = submit(term, frames, req_id, key_ver, wrap)
        if response.get("ok") is not True and response.get("error") == code and audit_hit(env, admin.token, req_id, code):
            identified += 1
        else:
            print("TAMPER", req_id, response.get("error"), flush=True)

    def flip_ct(blob):
        _, _, ct = span_after(blob, 18)
        blob[ct[0]] ^= 0x01

    def flip_mac(blob):
        blob[-1] ^= 0x01

    def swap_tenant(blob):
        tenant, _, _ = span_after(blob, 18)
        if blob[tenant[0]:tenant[1]] != b"tenant-a":
            raise RuntimeError("tenant span")
        blob[tenant[0]:tenant[1]] = b"tenant-b"

    def flip_key_ver(blob):
        blob[6] ^= 0x01

    def flip_req(blob):
        tenant, _, _ = span_after(blob, 18)
        blob[tenant[1] + 2] ^= 0x01

    def flip_obj(blob):
        blob[5] = 99

    tamper("tamper-ct", flip_ct, "TAG_FAIL")
    tamper("tamper-mac", flip_mac, "TAG_FAIL")
    tamper("tamper-tenant", swap_tenant, "AUTHZ_DENY")
    tamper("tamper-ver", flip_key_ver, "TAG_FAIL")
    tamper("tamper-req", flip_req, "AUTHZ_DENY")
    tamper("tamper-obj", flip_obj, "FRAME")
    out_dek, out_ver, out_wrap, out_frames = make_frames(term, base, "tamper-out")
    produced = submit(term, out_frames, "tamper-out", out_ver, out_wrap)
    output_rejected = False
    if produced.get("ok") and produced.get("output_frame"):
        mutated = bytearray(b64d(produced["output_frame"]))
        mutated[-1] ^= 0x01
        try:
            open_frame(out_dek, bytes(mutated))
        except CryptoError as exc:
            output_rejected = exc.code == "TAG_FAIL"
    tool_dek, tool_ver, tool_wrap, tool_frames = make_frames(term, base, "tamper-tool")
    tool_frames["tool_arg"] = b64e(seal(tool_dek, "tool_arg", term.tenant, "tamper-tool", tool_ver, "{\"city\":\"北京\"}".encode("utf-8")))
    tool_blob = bytearray(b64d(tool_frames["tool_arg"]))
    _, _, tool_ct = span_after(tool_blob, 18)
    tool_blob[tool_ct[0]] ^= 0x01
    tool_frames["tool_arg"] = b64e(bytes(tool_blob))
    tool_resp = submit(term, tool_frames, "tamper-tool", tool_ver, tool_wrap)
    tool_identified = tool_resp.get("ok") is not True and tool_resp.get("error") == "TAG_FAIL" and audit_hit(env, admin.token, "tamper-tool", "TAG_FAIL")
    if not tool_identified:
        print("TAMPER TOOL", tool_resp.get("error"), flush=True)
    mark("M3 篡改", identified == 6 and output_rejected and tool_identified, f"server={identified}/6 output={output_rejected} tool={tool_identified}")

    replay_ok = 0
    _, key_ver, wrap, frames = make_frames(term, base, "replay-1")
    used_prompt = b64d(frames["prompt"])
    first = submit(term, frames, "replay-1", key_ver, wrap)
    second = submit(term, frames, "replay-1", key_ver, wrap)
    if first.get("ok") is True and second.get("error") == "REPLAY" and audit_hit(env, admin.token, "replay-1", "REPLAY"):
        replay_ok += 1
    else:
        print("REPLAY", first.get("error"), second.get("error"), flush=True)
    _, key_ver, wrap, frames = make_frames(term, base, "window-1")
    blob = bytearray(b64d(frames["prompt"]))
    blob[10:18] = b"\x00" * 8
    frames["prompt"] = b64e(bytes(blob))
    window = submit(term, frames, "window-1", key_ver, wrap)
    if window.get("error") == "WINDOW" and audit_hit(env, admin.token, "window-1", "WINDOW"):
        replay_ok += 1
    else:
        print("WINDOW", window.get("error"), flush=True)
    _, nonce_ver, nonce_wrap, fresh = make_frames(term, base, "nonce-2")
    old = bytearray(used_prompt)
    new = bytearray(b64d(fresh["prompt"]))
    _, old_nonce, _ = span_after(old, 18)
    _, new_nonce, _ = span_after(new, 18)
    new[new_nonce[0]:new_nonce[1]] = old[old_nonce[0]:old_nonce[1]]
    fresh["prompt"] = b64e(bytes(new))
    nonce_resp = submit(term, fresh, "nonce-2", nonce_ver, nonce_wrap)
    if nonce_resp.get("error") == "REPLAY" and audit_hit(env, admin.token, "nonce-2", "REPLAY"):
        replay_ok += 1
    else:
        print("NONCE", nonce_resp.get("error"), flush=True)
    mark("M4 重放", replay_ok == 3, f"{replay_ok}/3")

    print(f"warmup {warmup}", flush=True)
    warm_off = []
    for item in prompts[:warmup]:
        warmed = term.infer(item["prompt"], tool_args={"city": "北京"}, protect=False)
        warm_off.append(warmed["latency_ms"])
        term.infer(item["prompt"], tool_args={"city": "北京"}, protect=True)
    baseline = sorted(warm_off)[len(warm_off) // 2]
    print(f"baseline_off {baseline:.1f}", flush=True)

    success = 0
    hits = 0
    qualified = 0
    stopped = False
    deltas = []
    m1_hashes = []
    raw_dir = ROOT / "data" / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    m1_path = raw_dir / ("m1.jsonl" if full else "probe-m1.jsonl")
    m5_path = raw_dir / ("m5.jsonl" if full else "probe-m5.jsonl")
    with m1_path.open("w", encoding="utf-8", newline="\n") as m1, m5_path.open("w", encoding="utf-8", newline="\n") as m5:
        busy = 0
        for index, item in enumerate(prompts[:n_pair]):
            on_first = index % 2 == 1
            while True:
                first = term.infer(item["prompt"], tool_args={"city": "北京"}, protect=on_first)
                if first["latency_ms"] <= baseline * 1.5:
                    busy = 0
                    break
                busy += 1
                print(f"STALL first {first['latency_ms']:.0f} base {baseline:.0f}", flush=True)
                if busy >= 5:
                    print("STOP machine busy", flush=True)
                    print("FAILED ['machine busy']", flush=True)
                    return 1
                time.sleep(2)
            second = term.infer(item["prompt"], tool_args={"city": "北京"}, protect=not on_first)
            off, on = (second, first) if on_first else (first, second)
            off_line = raw_line(off)
            on_line = raw_line(on)
            off_line["order"] = "on-off" if on_first else "off-on"
            on_line["order"] = off_line["order"]
            m5.write(json.dumps(off_line, ensure_ascii=False) + "\n")
            m5.write(json.dumps(on_line, ensure_ascii=False) + "\n")
            m1.write(json.dumps(raw_line(on), ensure_ascii=False) + "\n")
            if protected_ok(on):
                success += 1
                m1_hashes.append(on["audit_hash"])
            if on["ok"] and on.get("doc_ids") == [item["doc_id"]]:
                hits += 1
            delta = on["latency_ms"] - off["latency_ms"]
            deltas.append(delta)
            if off["ok"] and on["ok"] and (delta <= 30 or delta <= 0.15 * off["latency_ms"]):
                qualified += 1
            elif full is False:
                print(
                    "PAIR",
                    index,
                    round(off["latency_ms"], 1),
                    round(delta, 1),
                    "llama",
                    off.get("llama_ms"),
                    on.get("llama_ms"),
                    "tok",
                    off.get("completion_tokens"),
                    on.get("completion_tokens"),
                    flush=True,
                )
            if index % 25 == 24:
                m1.flush()
                m5.flush()
                print(f"PROGRESS pair {index + 1}/{n_pair} ok {success} qualified {qualified}", flush=True)
            if full and index + 1 in (100, 200) and qualified < 0.90 * (index + 1):
                print(f"STOP latency {qualified}/{index + 1}", flush=True)
                stopped = True
                break
    if stopped:
        print("FAILED ['M5/M6 early']", flush=True)
        return 1
    mark("M1 请求数", n_pair == (1000 if full else 30), f"{n_pair}")
    mark("M2 保护成功", n_pair > 0 and success / n_pair >= (0.995 if full else 0.995), f"{success}/{n_pair}")
    mark("知识库命中", n_pair > 0 and hits / n_pair >= 0.95, f"{hits}/{n_pair}")
    ratio = qualified / n_pair if n_pair else 0
    shown = [round(item, 1) for item in deltas[:20]]
    mark("M5/M6 时延", ratio >= 0.95, f"{qualified}/{n_pair} ratio={ratio:.4f} head={shown} max={round(max(deltas), 1) if deltas else None}")
    slot_dir = Path(r"C:\Users\zhaoc\Desktop\a117-slots")
    slot_dir.mkdir(parents=True, exist_ok=True)
    for old in slot_dir.glob("*"):
        old.unlink()
    slot_req = urllib.request.Request(
        f"http://127.0.0.1:{LLAMA_PORT}/slots/0?action=save",
        data=json.dumps({"filename": "kv.bin"}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    print("slot save", flush=True)
    slot_note = ""
    slot_ok = False
    try:
        with urllib.request.urlopen(slot_req, timeout=120) as resp:
            slot_note = resp.read().decode("utf-8", "replace")[:180]
        slot_path = slot_dir / "kv.bin"
        if slot_path.exists() and slot_path.stat().st_size > 0:
            slot_dek, slot_ver, _ = term.issue_dek()
            sealed_path = slot_dir / "kv-sealed.bin"
            total = slot_path.stat().st_size
            first_plain = b""
            with slot_path.open("rb") as src, sealed_path.open("wb") as dst:
                index = 0
                while True:
                    piece = src.read(256 * 1024)
                    if not piece:
                        break
                    if index == 0:
                        first_plain = piece
                    frame = seal(slot_dek, "kv_block", term.tenant, f"slot-{index}", slot_ver, piece)
                    dst.write(len(frame).to_bytes(4, "big") + frame)
                    index += 1
                    if index % 10 == 0:
                        print("slot chunk", index, flush=True)
            slot_path.unlink()
            with sealed_path.open("rb") as handle:
                size = int.from_bytes(handle.read(4), "big")
                frame = handle.read(size)
            _, restored = open_frame(slot_dek, frame)
            slot_ok = restored == first_plain and not slot_path.exists() and sealed_path.stat().st_size > total
            slot_note = f"bytes={total} chunks={index} restored={restored == first_plain}"
    except Exception as exc:
        slot_note = str(exc)[:300]
    mark("KV槽", slot_ok, slot_note)

    box = {"stop": False, "rows": []}
    lock = threading.Lock()
    twins = []
    for _ in range(4):
        twin = Terminal(term.kms, term.gateway, term.tenant, term.private, term.public)
        twin.login()
        twins.append(twin)

    def worker(local):
        while not box["stop"]:
            item = local.infer(prompts[0]["prompt"], tool_args={"city": "北京"}, protect=True)
            with lock:
                box["rows"].append(item)

    workers = [threading.Thread(target=worker, args=(twins[i],), name=f"infer-{i}", daemon=True) for i in range(4)]
    for worker_thread in workers:
        worker_thread.start()
    time.sleep(0.3)
    rotates = []
    for index in range(n_rot):
        admin.ensure()
        _, response = post_json(env["kms"] + "/v1/rotate", {"token": admin.token, "tenant_id": "tenant-a"})
        rotates.append(response)
        if (index + 1) % 20 == 0:
            print(f"PROGRESS rotate {index + 1}/{n_rot}", flush=True)
    begin = rotates[0].get("t_begin", 0) if rotates else 0
    deadline = time.time() + (180 if full else 60)
    while time.time() < deadline:
        with lock:
            ready = sum(1 for item in box["rows"] if item["t_start"] >= begin)
        if ready >= n_win:
            break
        time.sleep(0.05)
    else:
        print(f"WINDOW TIMEOUT ready={ready}", flush=True)
    box["stop"] = True
    for worker_thread in workers:
        worker_thread.join(timeout=180)
    state_ok = sum(1 for item in rotates if item.get("ok") and item.get("state_ok") is True)
    admin.ensure()
    _, status = post_json(env["kms"] + "/v1/status", {"token": admin.token, "tenant_id": "tenant-a"})
    mark("M7 换钥次数", len(rotates) >= (100 if full else n_rot) and len(rotates) == n_rot, f"{len(rotates)}")
    mark("M8 换钥成功", n_rot > 0 and state_ok / n_rot >= 0.99 and status.get("active_count") == 1, f"{state_ok}/{n_rot} active={status.get('active_count')}")

    live = Store(env["store_path"])
    try:
        live.unwrap_dek("tenant-a", saved_ver, saved_wrap)
        decrypt_only_ok = True
    except Exception as exc:
        decrypt_only_ok = False
        print("DECRYPT_ONLY", exc, flush=True)
    live.close()

    retired = 0
    for version in status.get("versions") or []:
        if version["state"] == "DecryptOnly":
            admin.ensure()
            _, response = post_json(
                env["kms"] + "/v1/kek/retire",
                {"token": admin.token, "tenant_id": "tenant-a", "version": version["version"]},
            )
            retired += int(bool(response.get("ok")))
    t_retire = time.time()
    with lock:
        window_rows = [item for item in box["rows"] if begin <= item["t_start"] <= t_retire]
    window_ok = sum(1 for item in window_rows if protected_ok(item))
    mark(
        "M9 换钥中请求",
        len(window_rows) >= n_win and window_ok / len(window_rows) >= 0.995,
        f"{window_ok}/{len(window_rows)}",
    )
    key_path = raw_dir / ("m7.jsonl" if full else "probe-m7.jsonl")
    with key_path.open("w", encoding="utf-8", newline="\n") as handle:
        for index, item in enumerate(rotates):
            handle.write(json.dumps({
                "op_id": f"rot-{index}",
                "t_commit": item.get("t_commit"),
                "tenant_id": "tenant-a",
                "old_ver": item.get("old_ver"),
                "new_ver": item.get("new_ver"),
                "state_ok": bool(item.get("state_ok")),
                "inflight_ok": window_ok,
                "inflight_total": len(window_rows),
            }, ensure_ascii=False) + "\n")

    live = Store(env["store_path"])
    retired_denied = False
    try:
        live.unwrap_dek("tenant-a", saved_ver, saved_wrap)
    except Exception:
        retired_denied = True
    live.close()
    admin.ensure()
    _, active_revoke = post_json(
        env["kms"] + "/v1/kek/revoke",
        {"token": admin.token, "tenant_id": "tenant-a", "version": status.get("active_version")},
    )
    _, old_revoke = post_json(
        env["kms"] + "/v1/kek/revoke",
        {"token": admin.token, "tenant_id": "tenant-a", "version": saved_ver},
    )
    _, recover = post_json(
        env["kms"] + "/v1/kek/recover",
        {"token": admin.token, "tenant_id": "tenant-a", "version": saved_ver},
    )
    copy_path = ROOT / "var" / "kms-crash.sqlite"
    src = sqlite3.connect(env["store_path"])
    dst = sqlite3.connect(copy_path)
    src.backup(dst)
    dst.close()
    src.close()
    pre = Store(str(copy_path))
    before = pre.status("tenant-a")
    pre.close()
    crashed = subprocess.run([sys.executable, str(ROOT / "tests" / "crash_rotate.py"), str(copy_path), "tenant-a"])
    post = Store(str(copy_path))
    after_kill = post.status("tenant-a")
    raised = False
    try:
        post.rotate("tenant-a", abort="raise")
    except RuntimeError as exc:
        raised = "ABORT_BEFORE_COMMIT" in str(exc)
    after_raise = post.status("tenant-a")
    post.close()
    mark(
        "E9 状态",
        decrypt_only_ok
        and retired_denied
        and active_revoke.get("ok") is False
        and old_revoke.get("ok") is True
        and recover.get("result") == "REVOKED_DENIED"
        and crashed.returncode == 137
        and after_kill["active_version"] == before["active_version"]
        and after_kill["active_count"] == 1
        and raised
        and after_raise["active_version"] == before["active_version"]
        and after_raise["active_count"] == 1,
        f"decrypt_only={decrypt_only_ok} retired_deny={retired_denied} active_revoke={active_revoke.get('ok')} recover={recover.get('result')} crash={crashed.returncode} kill_ver={after_kill['active_version']}/{before['active_version']}",
    )

    term.ensure()
    other.ensure()
    _, key_a = post_json(env["sidecar"] + "/v1/cache-key", {"token": term.token, "prompt": base, "salt": "attacker-salt"})
    _, key_a2 = post_json(env["sidecar"] + "/v1/cache-key", {"token": term.token, "prompt": base, "salt": "other-salt"})
    other.ensure()
    _, key_b = post_json(env["sidecar"] + "/v1/cache-key", {"token": other.token, "prompt": base, "salt": "attacker-salt"})
    _, crossed = post_json(env["kb"] + "/v1/cross-open", {"token": other.token, "victim": "tenant-a"})
    loaded_b = env["kb_obj"].load_sealed("tenant-b")
    loaded_a = env["kb_obj"].load_sealed("tenant-a")
    sealed = (ROOT / "var" / "kb" / "tenant-a.jsonl").read_text(encoding="utf-8").splitlines()[1]
    broken = bytearray(b64d(json.loads(sealed)["frame"]))
    broken[-40] ^= 0x01
    corrupt = False
    try:
        open_frame(env["kb_obj"].keys["tenant-a"]["dek"], bytes(broken))
    except CryptoError as exc:
        corrupt = exc.code == "TAG_FAIL"
    req_id = "spill" + uuid.uuid4().hex[:12]
    dek, key_ver, wrap, frames = make_frames(term, prompt0, req_id)
    spilled = submit(term, frames, req_id, key_ver, wrap, spill=True)
    archive = ROOT / "var" / "archive" / "kv-last.bin"
    deadline = time.time() + 10
    while time.time() < deadline and not archive.exists():
        time.sleep(0.05)
    archive_plain = False
    archive_hidden = False
    archive_wrong = False
    temp_path = ROOT / "var" / "tmp" / "working.bin"
    temp_hidden = False
    temp_plain = False
    if temp_path.exists() and spilled.get("ok"):
        tblob = temp_path.read_bytes()
        temp_hidden = title_b not in tblob
        _, tplain = open_frame(dek, tblob)
        temp_plain = title in tplain.decode("utf-8")
        env["side_obj"].clear_temp()
    temp_gone = not temp_path.exists()
    if archive.exists() and spilled.get("ok"):
        blob = archive.read_bytes()
        archive_hidden = title_b not in blob
        _, plain = open_frame(dek, blob)
        archive_plain = title in plain.decode("utf-8")
        try:
            open_frame(os.urandom(16), blob)
        except CryptoError as exc:
            archive_wrong = exc.code == "TAG_FAIL"
    mark(
        "E8 隔离",
        key_a.get("cache_key")
        and key_a.get("cache_key") == key_a2.get("cache_key")
        and key_a.get("cache_key") != key_b.get("cache_key")
        and crossed.get("opened") is False
        and loaded_a == 24
        and loaded_b == 24
        and corrupt
        and archive_hidden
        and archive_plain
        and archive_wrong
        and temp_hidden
        and temp_plain
        and temp_gone,
        f"cache={bool(key_a.get('cache_key'))} differ={key_a.get('cache_key') != key_b.get('cache_key')} loaded={loaded_a}/{loaded_b} corrupt={corrupt} hidden={archive_hidden} temp={temp_hidden}/{temp_gone} cross={crossed.get('error')} err={key_a.get('error')}",
    )

    admin.ensure()
    term.login()
    exp = int(term.token["claims"]["exp"])
    jti = term.token["claims"]["jti"]
    _, revoked = post_json(env["kms"] + "/v1/revoke", {"token": admin.token, "jti": jti})
    t0 = revoked.get("t0")
    if full:
        marks_at = [float(i) for i in range(1, 59, 2)]
        marks_at.append(min(59.0, max(1.0, exp - t0 - 1.0)))
    else:
        marks_at = [0.3, 0.8, 1.2]
    revoke_rows = []
    denied = 0
    for mark_at in marks_at:
        delay = t0 + mark_at - time.time()
        if delay > 0:
            time.sleep(delay)
        sent_at = time.time()
        item = term.infer(prompts[0]["prompt"], protect=True, refresh=False)
        in_window = t0 < sent_at <= t0 + 60
        accepted = bool(item["ok"])
        if sent_at < exp - 0.3:
            rejected = item["error_code"] == "AUTH_REVOKED"
        else:
            rejected = not accepted
        if in_window and rejected:
            denied += 1
        revoke_rows.append({"jti": jti, "t0": t0, "t_req": sent_at, "accepted": accepted, "error": item["error_code"]})
        print(f"REVOKE +{sent_at - t0:.1f}s {item['error_code']}", flush=True)
    mark("M10/M11 吊销", revoked.get("ok") is True and denied == len(revoke_rows) and len(revoke_rows) == len(marks_at), f"{denied}/{len(revoke_rows)} t0={t0}")
    revoke_path = raw_dir / ("m11.jsonl" if full else "probe-m11.jsonl")
    with revoke_path.open("w", encoding="utf-8", newline="\n") as handle:
        for item in revoke_rows:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")
    term.login()
    control = term.infer(prompts[1]["prompt"], protect=True)
    mark("吊销后新凭据", protected_ok(control), control["error_code"] or "OK")

    chain_ok, chain_n, checkpoints, hashes = verify_chain(env)
    missing = [item for item in m1_hashes if item not in hashes]
    need_points = 1 if full else 0
    mark(
        "审计链",
        chain_ok and chain_n > 0 and checkpoints >= need_points and not missing,
        f"count={chain_n} checkpoints={checkpoints} missing={len(missing)}",
    )

    ordered = sorted(deltas)
    p95 = ordered[min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))] if ordered else None
    lines = [
        "# M1–M11 实验记录",
        "",
        f"阶段: {phase}",
        f"模型: {MODEL_PATH}",
        f"模型字节: {os.path.getsize(MODEL_PATH)}",
        f"GPU: {gpu_line()}",
        f"max_tokens: {LLAMA_MAX_TOKENS}",
        "ignore_eos: false",
        f"知识库: {env['manifest']['kb']['path']} sha256={env['manifest']['files'][0]['sha256']}",
        f"工具规格: {env['manifest']['tool']['path']} sha256={next(item['sha256'] for item in env['manifest']['files'] if item['path'].endswith('.yml'))}",
        "",
    ]
    for name, ok, detail in gates:
        lines.append(f"- {'PASS' if ok else 'FAIL'} {name}: {detail}")
    lines.append("")
    lines.append(f"时延中位数 {statistics.median(deltas):.1f} ms，P95 {p95:.1f} ms，最大 {max(deltas):.1f} ms。" if deltas else "无时延样本")
    even = [delta for index, delta in enumerate(deltas) if index % 2 == 0]
    odd = [delta for index, delta in enumerate(deltas) if index % 2 == 1]
    lines.append(
        "预热不进入分母。攻击样本不进入 M1。偶数对先不保护再保护，奇数对先保护再不保护。"
        f"先关后开的平均附加时延 {statistics.mean(even):.1f} ms，先开后关的平均附加时延 {statistics.mean(odd):.1f} ms。"
        "1000 次请求都带加密的工具参数；同一城市的实网结果在一小时内复用。"
        f"本次实网调用 {env['tool_obj'].live_calls} 次。"
    )
    report_dir = ROOT / "data" / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_name = "summary.md" if full else "probe.md"
    (report_dir / report_name).write_text("\n".join(lines) + "\n", encoding="utf-8")
    if full:
        (report_dir / "env.md").write_text("\n".join(lines[:12]) + "\n", encoding="utf-8")
        os.makedirs(ROOT / "data" / "audit", exist_ok=True)
        src_audit = open(env["audit_path"], "r", encoding="utf-8")
        dst_audit = open(ROOT / "data" / "audit" / "chain.jsonl", "w", encoding="utf-8", newline="\n")
        dst_audit.write(src_audit.read())
        src_audit.close()
        dst_audit.close()
    for name in ("m1.jsonl", "m5.jsonl", "m7.jsonl", "m11.jsonl", "probe-m1.jsonl", "probe-m5.jsonl", "probe-m7.jsonl", "probe-m11.jsonl"):
        src = raw_dir / name
        if src.exists():
            shutil.copy2(src, run_dir / name)
    shutil.copy2(report_dir / report_name, run_dir / report_name)
    if (ROOT / "data" / "audit" / "chain.jsonl").exists():
        shutil.copy2(ROOT / "data" / "audit" / "chain.jsonl", run_dir / "chain.jsonl")
    print("RUN_DIR", run_dir, flush=True)
    failed = [name for name, ok, _ in gates if not ok]
    print("FAILED" if failed else "ALL PASS", failed, flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print("ABORT", type(exc).__name__, exc, flush=True)
        raise
