import json
import os
import time
import uuid

from common.actor import Actor
from common.crypto import sha256_hex, sm3_digest, unwrap_key
from common.frame import open_frame, seal
from common.httputil import get_json, post_json


def b64d(text: str) -> bytes:
    import base64
    return base64.b64decode(text.encode("ascii"))


def b64e(data: bytes) -> str:
    import base64
    return base64.b64encode(data).decode("ascii")


class Terminal(Actor):
    def __init__(self, kms: str, gateway: str, tenant: str, private: str, public: str):
        super().__init__(kms, tenant, private, public)
        self.gateway = gateway

    def issue_dek(self, refresh=True):
        if refresh:
            self.ensure()
        _, response = post_json(self.kms + "/v1/dek", {"token": self.token})
        if not response.get("ok"):
            raise RuntimeError(response.get("error", "DEK"))
        dek = unwrap_key(self.skey, b64d(response["sealed_dek"]))
        return dek, int(response["key_ver"]), response["wrap"]

    def infer(self, prompt: str, tool_args=None, protect=True, refresh=True, max_tokens=None):
        if protect and refresh:
            self.ensure()
        req_id = uuid.uuid4().hex
        started_wall = time.time()
        started = time.perf_counter()
        mode = "on" if protect else "off"
        key_ver = 0
        error = ""
        content = ""
        tool = None
        doc_ids = []
        cache = ""
        leaked = None
        phase = {}
        try:
            if protect:
                dek, key_ver, wrap = self.issue_dek(refresh=False)
                phase["issue"] = round((time.perf_counter() - started) * 1000, 1)
                frames = {
                    "prompt": b64e(seal(dek, "prompt", self.tenant, req_id, key_ver, prompt.encode("utf-8"))),
                    "query": b64e(seal(dek, "query", self.tenant, req_id, key_ver, prompt.encode("utf-8"))),
                }
                if tool_args is not None:
                    raw = json.dumps(tool_args, ensure_ascii=False).encode("utf-8")
                    frames["tool_arg"] = b64e(seal(dek, "tool_arg", self.tenant, req_id, key_ver, raw))
                phase["seal"] = round((time.perf_counter() - started) * 1000, 1)
                _, response = post_json(
                    self.gateway + "/v1/infer",
                    {
                        "protect": True,
                        "token": self.token,
                        "req_id": req_id,
                        "key_ver": key_ver,
                        "wrap": wrap,
                        "frames": frames,
                        "max_tokens": max_tokens,
                    },
                    timeout=180,
                )
                phase["http"] = round((time.perf_counter() - started) * 1000, 1)
                if response.get("ok"):
                    _, plain = open_frame(dek, b64d(response["output_frame"]))
                    content = plain.decode("utf-8")
                    if response.get("tool_frame"):
                        _, tool_plain = open_frame(dek, b64d(response["tool_frame"]))
                        tool = json.loads(tool_plain.decode("utf-8"))
                    doc_ids = response.get("doc_ids") or []
                    cache = response.get("cache_key") or ""
                    leaked = response.get("upstream_leaked")
                else:
                    error = response.get("error", "FAIL")
            else:
                _, response = post_json(
                    self.gateway + "/v1/infer",
                    {"protect": False, "prompt": prompt, "tool_args": tool_args, "max_tokens": max_tokens},
                    timeout=180,
                )
                if response.get("ok"):
                    content = response.get("content") or ""
                    leaked = response.get("upstream_leaked")
                else:
                    error = response.get("error", "FAIL")
        except Exception as exc:
            error = str(exc)
            response = {"ok": False, "error": error}
        elapsed_ms = (time.perf_counter() - started) * 1000
        return {
            "ok": error == "" and bool(response.get("ok")),
            "req_id": req_id,
            "latency_ms": round(elapsed_ms, 3),
            "mode": mode,
            "tenant_id": self.tenant,
            "key_ver": key_ver,
            "jti": "" if not self.token else self.token["claims"]["jti"],
            "result": "OK" if error == "" else error,
            "error_code": error,
            "prompt_sha256": sha256_hex(prompt.encode("utf-8")),
            "prompt_sm3": sm3_digest(prompt.encode("utf-8")).hex(),
            "content": content,
            "tool": tool,
            "doc_ids": doc_ids,
            "cache_key": cache,
            "upstream_leaked": leaked,
            "llama_ms": response.get("llama_ms"),
            "completion_tokens": response.get("completion_tokens"),
            "phase": phase,
            "kb_ms": response.get("kb_ms"),
            "sc_ms": response.get("sc_ms"),
            "unwrap_ms": response.get("unwrap_ms"),
            "open_ms": response.get("open_ms"),
            "audit_hash": response.get("audit_hash") or "",
            "t_start": started_wall,
            "t_end": time.time(),
        }


def wait_health(url, timeout=30):
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        try:
            if get_json(url, timeout=2).get("ok"):
                return
        except Exception as exc:
            last = str(exc)
        time.sleep(0.1)
    raise RuntimeError(f"health {url} {last}")


def wipe(path):
    if os.path.isdir(path):
        for root, dirs, files in os.walk(path, topdown=False):
            for name in files:
                os.remove(os.path.join(root, name))
            for name in dirs:
                os.rmdir(os.path.join(root, name))
    os.makedirs(path, exist_ok=True)
