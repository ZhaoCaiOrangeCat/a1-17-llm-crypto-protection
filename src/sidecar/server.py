import json
import os
import queue
import threading
import time
import urllib.request

from common.actor import Actor, TokenChecker
from common.crypto import CryptoError, sm3_digest, unwrap_key
from common.frame import open_frame, seal
from common.httputil import post_json, serve
from common.prompt import build_user


def b64d(text: str) -> bytes:
    import base64
    return base64.b64decode(text.encode("ascii"))


def b64e(data: bytes) -> str:
    import base64
    return base64.b64encode(data).decode("ascii")


def cache_key(tenant: str, salt: bytes, prompt: str) -> str:
    return sm3_digest(tenant.encode("utf-8") + salt + sm3_digest(prompt.encode("utf-8"))).hex()


LLAMA_MAX_TOKENS = 64


def llama_complete(llama_url: str, model: str, user_text: str, max_tokens=None):
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "只依据给定资料和工具结果。用五句话回答，每句不少于三十字。不要输出思维过程。",
            },
            {"role": "user", "content": user_text},
        ],
        "max_tokens": LLAMA_MAX_TOKENS if max_tokens is None else int(max_tokens),
        "temperature": 0,
        "chat_template_kwargs": {"enable_thinking": False},
        "enable_thinking": False,
    }
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        llama_url, data=raw, headers={"Content-Type": "application/json; charset=utf-8"}
    )
    import time as _time
    t0 = _time.perf_counter()
    with urllib.request.urlopen(req, timeout=180) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    llama_ms = (_time.perf_counter() - t0) * 1000
    message = body["choices"][0]["message"]
    content = message.get("content") or ""
    leaked = b"api.open-meteo.com" in raw or b"geocoding-api.open-meteo.com" in raw
    llama_complete.last_raw = raw
    llama_complete.last_usage = body.get("usage")
    return content, leaked, len(raw), llama_ms


class Sidecar:
    def __init__(self, actor: Actor, checker: TokenChecker, llama_url: str, model: str, tmp_dir, archive_dir, store=None, audit_log=None):
        self.actor = actor
        self.checker = checker
        self.key_store = store
        self.audit_log = audit_log
        self.llama_url = llama_url
        self.model = model
        self.tmp_dir = tmp_dir
        self.archive_dir = archive_dir
        self.salts = {}
        self.spill_q = queue.Queue()
        self.spill_error = ""
        self.last_wire = b""
        self.last_llama = b""
        os.makedirs(tmp_dir, exist_ok=True)
        os.makedirs(archive_dir, exist_ok=True)
        threading.Thread(target=self._spill_loop, name="kv-spill", daemon=True).start()

    def _spill_loop(self):
        while True:
            item = self.spill_q.get()
            try:
                self.spill(*item)
            except Exception as exc:
                self.spill_error = str(exc)

    def note(self, claims, body, result):
        if self.audit_log is None or claims is None:
            return
        self.audit_log.append(
            {
                "ts": int(time.time()),
                "node": "sidecar",
                "tenant_id": claims["tenant_id"],
                "req_id": body.get("req_id", ""),
                "action": "infer",
                "result": result,
                "obj_type": "output",
                "key_ver": int(body.get("key_ver") or 0),
                "jti": claims.get("jti", ""),
            }
        )

    def salt(self, tenant: str) -> bytes:
        if tenant not in self.salts:
            self.actor.ensure()
            _, response = post_json(
                self.actor.kms + "/v1/salt",
                {"token": self.actor.token, "tenant_id": tenant},
            )
            if not response.get("ok"):
                raise RuntimeError(response.get("error", "SALT"))
            self.salts[tenant] = b64d(response["salt"])
        return self.salts[tenant]

    def spill(self, tenant: str, req_id: str, key_ver: int, dek: bytes, prompt: str):
        digest = cache_key(tenant, self.salt(tenant), prompt)
        payload = json.dumps(
            {"prompt": prompt, "req_id": req_id, "cache_key": digest},
            ensure_ascii=False,
        ).encode("utf-8")
        frame = seal(dek, "kv_block", tenant, req_id, key_ver, payload)
        safe = "last"
        archive = os.path.join(self.archive_dir, "kv-last.bin")
        temporary = archive + ".tmp"
        with open(temporary, "wb") as handle:
            handle.write(frame)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, archive)
        return digest

    def seal_temp(self, tenant: str, req_id: str, key_ver: int, dek: bytes, payload: bytes):
        if isinstance(payload, str):
            payload = payload.encode("utf-8")
        frame = seal(dek, "kv_block", tenant, req_id, key_ver, payload)
        temporary = os.path.join(self.tmp_dir, "working.bin")
        with open(temporary, "wb") as handle:
            handle.write(frame)
            handle.flush()
            os.fsync(handle.fileno())
        return temporary

    def clear_temp(self):
        temporary = os.path.join(self.tmp_dir, "working.bin")
        if os.path.exists(temporary):
            os.remove(temporary)

    def unwrap(self, claims, key_ver, wrap):
        try:
            return self.key_store.unwrap_dek(claims["tenant_id"], int(key_ver), b64d(wrap))
        except Exception as exc:
            raise RuntimeError(getattr(exc, "code", "WRAP_TAG")) from exc


def start_sidecar(actor, checker, llama_url, model, tmp_dir, archive_dir, host, port, store=None, audit_log=None):
    side = Sidecar(actor, checker, llama_url, model, tmp_dir, archive_dir, store, audit_log)

    def health(body, query):
        return 200, {"ok": True}

    def cache(body, query):
        claims, err = checker.require(body["token"], "infer")
        if err:
            return 200, {"ok": False, "error": err}
        digest = cache_key(claims["tenant_id"], side.salt(claims["tenant_id"]), body["prompt"])
        return 200, {"ok": True, "cache_key": digest}

    def generate_plain(body, query):
        tool_text = ""
        if body.get("tool"):
            tool_text = json.dumps(body["tool"], ensure_ascii=False, sort_keys=True)
        user = build_user(body["prompt"], body.get("passages") or [], tool_text)
        try:
            content, leaked, nbytes, llama_ms = llama_complete(side.llama_url, side.model, user, body.get("max_tokens"))
        except Exception as exc:
            return 200, {"ok": False, "error": "LLAMA_FAIL", "detail": str(exc)}
        return 200, {"ok": True, "content": content, "upstream_leaked": leaked, "llama_bytes": nbytes, "llama_ms": round(llama_ms, 2), "completion_tokens": (getattr(llama_complete, "last_usage", None) or {}).get("completion_tokens")}

    def generate(body, query):
        claims, err = checker.require(body["token"], "infer")
        if err:
            return 200, {"ok": False, "error": err}
        t0 = time.perf_counter()
        try:
            dek = side.unwrap(claims, body["key_ver"], body["wrap"])
            t_unwrap = time.perf_counter()
            prompt_meta, prompt = open_frame(dek, b64d(body["prompt_frame"]))
            retrieval_meta, retrieval_raw = open_frame(dek, b64d(body["retrieval_frame"]))
            if prompt_meta["obj_name"] != "prompt" or retrieval_meta["obj_name"] != "retrieval":
                raise CryptoError("AUTHZ_DENY")
            t_open = time.perf_counter()
            tool = None
            if body.get("tool_frame"):
                tool_meta, tool_raw = open_frame(dek, b64d(body["tool_frame"]))
                if tool_meta["obj_name"] != "tool_result":
                    raise CryptoError("AUTHZ_DENY")
                tool = json.loads(tool_raw.decode("utf-8"))
        except Exception as exc:
            code = getattr(exc, "code", None) or str(exc)
            side.note(claims, body, code)
            return 200, {"ok": False, "error": code}
        passages = json.loads(retrieval_raw.decode("utf-8"))
        tool_text = json.dumps(tool, ensure_ascii=False, sort_keys=True) if tool else ""
        user = build_user(prompt.decode("utf-8"), passages, tool_text)
        try:
            content, leaked, nbytes, llama_ms = llama_complete(side.llama_url, side.model, user, body.get("max_tokens"))
        except Exception as exc:
            side.note(claims, body, "LLAMA_FAIL")
            return 200, {"ok": False, "error": "LLAMA_FAIL", "detail": str(exc)}
        frame = seal(
            dek,
            "output",
            claims["tenant_id"],
            body["req_id"],
            int(body["key_ver"]),
            content.encode("utf-8"),
        )
        prompt_text = prompt.decode("utf-8")
        digest = cache_key(claims["tenant_id"], side.salt(claims["tenant_id"]), prompt_text)
        side.last_llama = getattr(llama_complete, "last_raw", b"") or b""
        if body.get("spill", False):
            side.seal_temp(claims["tenant_id"], body["req_id"], int(body["key_ver"]), dek, prompt)
            side.spill(claims["tenant_id"], body["req_id"], int(body["key_ver"]), dek, prompt_text)
        side.note(claims, body, "OK")
        return 200, {
            "ok": True,
            "output_frame": b64e(frame),
            "cache_key": digest,
            "upstream_leaked": leaked,
            "llama_bytes": nbytes,
            "llama_ms": round(llama_ms, 2),
            "completion_tokens": (getattr(llama_complete, "last_usage", None) or {}).get("completion_tokens"),
            "unwrap_ms": round((t_unwrap - t0) * 1000, 2),
            "open_ms": round((t_open - t_unwrap) * 1000, 2),
        }

    side.handle_generate = generate
    side.handle_generate_plain = generate_plain

    def sink(path, raw):
        if path in ("/v1/generate", "/v1/generate-plain"):
            side.last_wire = raw

    routes = {
        ("GET", "/v1/health"): health,
        ("POST", "/v1/cache-key"): cache,
        ("POST", "/v1/generate-plain"): generate_plain,
        ("POST", "/v1/generate"): generate,
    }
    return serve(host, port, routes, sink), side
