import json
import os
import queue
import threading

from common.crypto import sm2_verify, sm3_digest
from common.frame import canon
from common.httputil import serve


class AuditLog:
    def __init__(self, path, public: str, sign_fn):
        self.path = path
        self.public = public
        self.sign_fn = sign_fn
        self.lock = threading.Lock()
        self.prev = b"\x00" * 32
        self.rows = []
        self.q = queue.Queue()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.fp = open(path, "w", encoding="utf-8", newline="\n")
        threading.Thread(target=self._write_loop, name="audit-writer", daemon=True).start()

    def _write_loop(self):
        while True:
            row, to_sign = self.q.get()
            try:
                if to_sign is not None and self.sign_fn is not None:
                    row["checkpoint"] = self.sign_fn(to_sign)
                self.fp.write(json.dumps(row, ensure_ascii=False) + "\n")
                if row["n"] % 20 == 0:
                    self.fp.flush()
            finally:
                self.q.task_done()

    def append(self, record: dict) -> str:
        body = canon(record)
        with self.lock:
            digest = sm3_digest(self.prev + body)
            self.prev = digest
            n = len(self.rows) + 1
            row = {"n": n, "record": record, "hash": digest.hex(), "checkpoint": ""}
            self.rows.append(row)
            self.q.put((row, digest if n % 100 == 0 else None))
            return digest.hex()

    def verify(self):
        self.q.join()
        with self.lock:
            self.fp.flush()
            os.fsync(self.fp.fileno())
        prev = b"\x00" * 32
        count = 0
        with open(self.path, "r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                row = json.loads(line)
                count += 1
                digest = sm3_digest(prev + canon(row["record"]))
                if digest.hex() != row["hash"] or row["n"] != count:
                    return False, count
                if count % 100 == 0:
                    if not row["checkpoint"] or not sm2_verify(self.public, digest, row["checkpoint"]):
                        return False, count
                prev = digest
        return True, count


def start_audit(host, port, path, public, sign_fn):
    log = AuditLog(path, public, sign_fn)

    def health(body, query):
        return 200, {"ok": True}

    def append(body, query):
        digest = log.append(body["record"])
        return 200, {"ok": True, "hash": digest}

    def verify(body, query):
        ok, count = log.verify()
        return 200, {"ok": ok, "count": count, "tail": log.prev.hex()}

    def find(body, query):
        checker = getattr(log, "checker", None)
        if checker is None:
            return 200, {"ok": False, "error": "AUTHZ_DENY"}
        claims, err = checker.require(body.get("token"), None)
        if err:
            return 200, {"ok": False, "error": err}
        roles = claims.get("roles") or []
        if "audit_read" not in roles:
            asked = body.get("tenant_id")
            if asked and asked != claims["tenant_id"]:
                return 200, {"ok": False, "error": "AUTHZ_DENY"}
        req_id = body.get("req_id")
        result = body.get("result")
        with log.lock:
            rows = list(log.rows)
        hits = []
        for row in rows:
            rec = row["record"]
            if "audit_read" not in roles and rec.get("tenant_id") != claims["tenant_id"]:
                continue
            if req_id and rec.get("req_id") != req_id:
                continue
            if result and rec.get("result") != result:
                continue
            hits.append(rec)
        return 200, {"ok": True, "hits": hits, "n": len(hits)}

    routes = {
        ("GET", "/v1/health"): health,
        ("POST", "/v1/append"): append,
        ("GET", "/v1/verify"): verify,
        ("POST", "/v1/find"): find,
    }
    return serve(host, port, routes), log
