import json
import os
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from run_m1_m11 import b64d, ensure_llama, free_service_ports, make_frames, open_frame, submit
from common.crypto import CryptoError
from common.httputil import post_json
from runtime import boot


def main():
    print("llama", ensure_llama(), flush=True)
    free_service_ports()
    env = boot(str(ROOT), "http://127.0.0.1:18080/v1/chat/completions", "qwen3.5-9b")
    term = env["a"]
    other = env["b"]
    term.ensure()
    other.ensure()
    prompt = "请用五句话说明泡泡战士，每句不少于三十字。"
    title = "泡泡战士"
    _, key_a = post_json(env["sidecar"] + "/v1/cache-key", {"token": term.token, "prompt": prompt, "salt": "attacker-salt"})
    _, key_a2 = post_json(env["sidecar"] + "/v1/cache-key", {"token": term.token, "prompt": prompt, "salt": "other-salt"})
    _, key_b = post_json(env["sidecar"] + "/v1/cache-key", {"token": other.token, "prompt": prompt, "salt": "attacker-salt"})
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
    dek, key_ver, wrap, frames = make_frames(term, prompt, req_id)
    spilled = submit(term, frames, req_id, key_ver, wrap)
    archive = ROOT / "var" / "archive" / "kv-last.bin"
    deadline = time.time() + 10
    while time.time() < deadline and not archive.exists():
        time.sleep(0.05)
    archive_plain = archive_hidden = archive_wrong = False
    if archive.exists() and spilled.get("ok"):
        blob = archive.read_bytes()
        archive_hidden = title.encode("utf-8") not in blob
        _, plain = open_frame(dek, blob)
        archive_plain = title in plain.decode("utf-8")
        try:
            open_frame(os.urandom(16), blob)
        except CryptoError as exc:
            archive_wrong = exc.code == "TAG_FAIL"
    ok = (
        bool(key_a.get("cache_key"))
        and key_a.get("cache_key") == key_a2.get("cache_key")
        and key_a.get("cache_key") != key_b.get("cache_key")
        and crossed.get("opened") is False
        and loaded_a == 24
        and loaded_b == 24
        and corrupt
        and archive_hidden
        and archive_plain
        and archive_wrong
    )
    print(
        "E8",
        "PASS" if ok else "FAIL",
        f"cache={bool(key_a.get('cache_key'))} same={key_a.get('cache_key')==key_a2.get('cache_key')} differ={key_a.get('cache_key')!=key_b.get('cache_key')} cross={crossed.get('error')} opened={crossed.get('opened')} loaded={loaded_a}/{loaded_b} corrupt={corrupt} hidden={archive_hidden} plain={archive_plain} wrong={archive_wrong} spill={spilled.get('error') or 'OK'}",
        flush=True,
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
