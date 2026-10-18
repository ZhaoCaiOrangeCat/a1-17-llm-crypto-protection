import base64
import json
import time

from common.actor import TokenChecker
from common.crypto import CryptoError
from common.frame import parse_frame
from common.httputil import post_json, serve


def b64d(text: str) -> bytes:
    return base64.b64decode(text.encode("ascii"))


class NonceCache:
    def __init__(self):
        self.items = {}

    def check(self, tenant: str, nonce: bytes, ts: int):
        now = int(time.time())
        if abs(now - int(ts)) > 60:
            return "WINDOW"
        key = (tenant, nonce)
        expired = [item for item, seen in self.items.items() if now - seen > 120]
        for item in expired:
            self.items.pop(item, None)
        if key in self.items:
            return "REPLAY"
        self.items[key] = now
        return None


class Gateway:
    def __init__(self, checker: TokenChecker, kb: str, tool: str, sidecar: str, audit: str, audit_log=None, kb_obj=None, tool_obj=None, side_obj=None):
        self.checker = checker
        self.kb = kb
        self.tool = tool
        self.sidecar = sidecar
        self.kb_obj = kb_obj
        self.tool_obj = tool_obj
        self.side_obj = side_obj
        self.audit_url = audit
        self.audit_log = audit_log
        self.nonces = NonceCache()
        self.last_forward = b""

    def audit(self, **record):
        if self.audit_log is not None:
            return self.audit_log.append(record)
        _, response = post_json(self.audit_url + "/v1/append", {"record": record}, timeout=5)
        return response.get("hash", "")

    def reject(self, claims, req_id, result, key_ver=0):
        digest = self.audit(
            ts=int(time.time()),
            node="gateway",
            tenant_id="" if claims is None else claims.get("tenant_id", ""),
            req_id=req_id or "",
            action="infer",
            result=result,
            obj_type="prompt",
            key_ver=int(key_ver or 0),
            jti="" if claims is None else claims.get("jti", ""),
        )
        return 200, {"ok": False, "error": result, "audit_hash": digest or ""}


def start_gateway(checker, kb, tool, sidecar, audit, host, port, audit_log=None, kb_obj=None, tool_obj=None, side_obj=None):
    gate = Gateway(checker, kb, tool, sidecar, audit, audit_log, kb_obj, tool_obj, side_obj)

    def health(body, query):
        return 200, {"ok": True}

    def scan(body, query):
        needle = body.get("needle", "").encode("utf-8")
        return 200, {"ok": True, "found": needle in gate.last_forward, "nbytes": len(gate.last_forward)}

    def infer(body, query):
        if not body.get("protect", True):
            return plain(body)
        claims, err = gate.checker.require(body.get("token"), "infer")
        req_id = body.get("req_id", "")
        if err:
            return gate.reject(claims, req_id, err, body.get("key_ver", 0))
        frames = body.get("frames") or {}
        parsed = {}
        for name, encoded in frames.items():
            try:
                item = parse_frame(b64d(encoded))
            except CryptoError:
                return gate.reject(claims, req_id, "FRAME", body.get("key_ver", 0))
            if item["tenant"] != claims["tenant_id"] or item["req_id"] != req_id or item["obj_name"] != name:
                return gate.reject(claims, req_id, "AUTHZ_DENY", item["key_ver"])
            problem = gate.nonces.check(item["tenant"], item["nonce"], item["ts"])
            if problem:
                return gate.reject(claims, req_id, problem, item["key_ver"])
            parsed[name] = item
        if "prompt" not in frames or "query" not in frames:
            return gate.reject(claims, req_id, "FRAME", body.get("key_ver", 0))
        g0 = time.perf_counter()
        kb_body = {
            "protect": True,
            "token": body["token"],
            "key_ver": body["key_ver"],
            "wrap": body["wrap"],
            "query_frame": frames["query"],
        }
        _, found = post_json(gate.kb + "/v1/search", kb_body, timeout=60)
        if not found.get("ok"):
            return gate.reject(claims, req_id, found.get("error", "KB"), body["key_ver"])
        g1 = time.perf_counter()
        tool_frame = None
        if frames.get("tool_arg"):
            _, called = post_json(
                gate.tool + "/v1/call",
                {
                    "protect": True,
                    "token": body["token"],
                    "key_ver": body["key_ver"],
                    "wrap": body["wrap"],
                    "tool_frame": frames["tool_arg"],
                },
                timeout=60,
            )
            if not called.get("ok"):
                return gate.reject(claims, req_id, called.get("error", "TOOL"), body["key_ver"])
            tool_frame = called["tool_frame"]
        forward = {
            "token": body["token"],
            "key_ver": body["key_ver"],
            "wrap": body["wrap"],
            "req_id": req_id,
            "prompt_frame": frames["prompt"],
            "retrieval_frame": found["retrieval_frame"],
            "tool_frame": tool_frame,
            "max_tokens": body.get("max_tokens"),
        }
        if body.get("spill"):
            forward["spill"] = True
        gate.last_forward = json.dumps(forward, ensure_ascii=False).encode("utf-8")
        _, generated = post_json(gate.sidecar + "/v1/generate", forward, timeout=180)
        result = "OK" if generated.get("ok") else generated.get("error", "FAIL")
        digest = gate.audit(
            ts=int(time.time()),
            node="gateway",
            tenant_id=claims["tenant_id"],
            req_id=req_id,
            action="infer",
            result=result,
            obj_type="output",
            key_ver=int(body["key_ver"]),
            jti=claims["jti"],
        )
        generated["audit_hash"] = digest or ""
        generated["doc_ids"] = found.get("doc_ids", [])
        generated["kb_ms"] = round((g1 - g0) * 1000, 2)
        generated["sc_ms"] = round((time.perf_counter() - g1) * 1000, 2)
        if tool_frame:
            generated["tool_frame"] = tool_frame
        return 200, generated

    def plain(body):
        _, found = post_json(
            gate.kb + "/v1/search",
            {"protect": False, "query": body.get("prompt", "")},
            timeout=60,
        )
        tool_result = None
        if body.get("tool_args"):
            _, called = post_json(
                gate.tool + "/v1/call",
                {"protect": False, "args": body["tool_args"]},
                timeout=60,
            )
            if not called.get("ok"):
                return 200, called
            tool_result = called["result"]
        _, generated = post_json(
            gate.sidecar + "/v1/generate-plain",
            {
                "prompt": body.get("prompt", ""),
                "passages": found.get("passages", []),
                "tool": tool_result,
                "max_tokens": body.get("max_tokens"),
            },
            timeout=180,
        )
        return 200, generated

    routes = {
        ("GET", "/v1/health"): health,
        ("POST", "/v1/infer"): infer,
        ("POST", "/v1/scan"): scan,
    }
    return serve(host, port, routes), gate
