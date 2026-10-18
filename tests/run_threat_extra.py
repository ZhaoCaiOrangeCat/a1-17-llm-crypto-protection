import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from common.crypto import sm2_keypair, sm2_sign
from common.httputil import post_json
from run_m1_m11 import b64e, ensure_llama, free_service_ports, make_frames, submit
from runtime import boot

OUT = ROOT / "data" / "logs" / "threat-extra.log"
RAW = ROOT / "data" / "raw" / "threat-extra.jsonl"


def record(rows, name, ok, detail):
    rows.append({"name": name, "ok": ok, "detail": detail, "t": time.time()})
    print(f"{'PASS' if ok else 'FAIL'} {name} {detail}", flush=True)
    return ok


def main():
    print("llama", ensure_llama(), flush=True)
    free_service_ports()
    env = boot(str(ROOT), "http://127.0.0.1:18080/v1/chat/completions", "qwen3.5-9b")
    term = env["a"]
    rows = []
    title = "泡泡战士"
    prompt = f"根据资料，用一句话说明{title}。"

    _, challenge = post_json(env["kms"] + "/v1/challenge", {"tenant_id": "tenant-a"})
    private, public = sm2_keypair()
    message = f"{challenge['challenge']}|tenant-a|{challenge['ts']}".encode()
    _, forged_login = post_json(
        env["kms"] + "/v1/login",
        {
            "tenant_id": "tenant-a",
            "challenge": challenge["challenge"],
            "signature": sm2_sign(private, public, message),
        },
    )
    record(rows, "伪造私钥登录", forged_login.get("error") == "AUTH_BAD_SIG", forged_login.get("error"))

    bad = json.loads(json.dumps(term.token))
    bad["sign"] = ("0" if bad["sign"][-1] != "0" else "1") + bad["sign"][1:]
    _, bad_sig = post_json(
        env["gateway"] + "/v1/infer",
        {"protect": True, "token": bad, "req_id": "forge-sig", "key_ver": 1, "wrap": "", "frames": {}},
        timeout=30,
    )
    record(rows, "伪造令牌签名", bad_sig.get("error") == "AUTH_BAD_SIG", bad_sig.get("error"))

    term.issue_dek()
    swapped = json.loads(json.dumps(term.token))
    swapped["claims"]["tenant_id"] = "tenant-b"
    swapped["claims"]["roles"] = ["infer", "key_rotate", "audit_read"]
    _, swapped_resp = post_json(
        env["gateway"] + "/v1/infer",
        {"protect": True, "token": swapped, "req_id": "forge-claims", "key_ver": 1, "wrap": "", "frames": {}},
        timeout=30,
    )
    record(rows, "篡改已缓存令牌声明", swapped_resp.get("error") == "AUTH_BAD_SIG", swapped_resp.get("error"))

    _, key_ver, wrap, frames = make_frames(term, prompt, "obj-slot")
    frames["tool_arg"] = frames["prompt"]
    obj_resp = submit(term, frames, "obj-slot", key_ver, wrap)
    record(rows, "对象类型与槽位不符", obj_resp.get("error") == "AUTHZ_DENY", obj_resp.get("error"))

    sniffed = term.infer(prompt, tool_args={"city": "北京"}, protect=True)
    wire = env["side_obj"].last_wire or b""
    _, scan = post_json(env["gateway"] + "/v1/scan", {"needle": title})
    secret = env["tool_obj"].secret.encode("utf-8")
    sniff_ok = (
        sniffed["ok"]
        and scan.get("found") is False
        and title.encode("utf-8") not in wire
        and b"api.open-meteo.com" not in wire
        and secret not in wire
        and len(wire) > 0
    )
    record(
        rows,
        "嗅探报文",
        sniff_ok,
        f"wire={len(wire)} forward_hit={scan.get('found')} err={sniffed['error_code']}",
    )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    RAW.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# 威胁补充检测", ""]
    for row in rows:
        lines.append(f"- {'PASS' if row['ok'] else 'FAIL'} {row['name']}: {row['detail']}")
    lines.append("")
    lines.append("进程内存中的明文不在检测范围内。")
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with RAW.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    failed = [row["name"] for row in rows if not row["ok"]]
    print("FAILED" if failed else "ALL PASS", failed, flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print("ABORT", type(exc).__name__, exc, flush=True)
        raise
