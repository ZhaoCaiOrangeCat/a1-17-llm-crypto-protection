import json
import math
import shutil
import time
from pathlib import Path

from common.actor import Actor, TokenChecker
from common.crypto import unwrap_key
from common.frame import open_frame, seal
from common.httputil import post_json, serve


def b64d(text: str) -> bytes:
    import base64
    return base64.b64decode(text.encode("ascii"))


def b64e(data: bytes) -> str:
    import base64
    return base64.b64encode(data).decode("ascii")


DIM = 4096


def features(text: str):
    from common.crypto import sm3_digest
    compact = "".join(text.split())
    counts = [0.0] * DIM
    if len(compact) < 2:
        return counts
    for index in range(len(compact) - 1):
        gram = compact[index:index + 2].encode("utf-8")
        bucket = int.from_bytes(sm3_digest(gram)[:2], "big") % DIM
        counts[bucket] += 1.0
    return counts


def normalize(values):
    norm = math.sqrt(sum(v * v for v in values)) or 1.0
    return [v / norm for v in values]


class Knowledge:
    def __init__(self, actor: Actor, checker: TokenChecker, corpus: Path, store_dir: Path, tenants: list, store=None):
        self.actor = actor
        self.checker = checker
        self.key_store = store
        self.corpus = corpus
        self.store_dir = store_dir
        self.tenants = tenants
        self.docs = []
        self.keys = {}
        self.store_dir.mkdir(parents=True, exist_ok=True)

    def load_corpus(self):
        docs = []
        for line in self.corpus.read_text(encoding="utf-8").splitlines():
            if line.strip():
                docs.append(json.loads(line))
        raw = []
        for doc in docs:
            raw.append({**doc, "tf": features(((doc["title"] + "\n") * 3) + doc["text"])})
        df = [0] * DIM
        for doc in raw:
            for index, value in enumerate(doc["tf"]):
                if value:
                    df[index] += 1
        total = len(raw)
        idf = [math.log((total + 1) / (df[i] + 1)) + 1 for i in range(DIM)]
        built = []
        for doc in raw:
            vec = normalize([doc["tf"][i] * idf[i] for i in range(DIM)])
            built.append({"doc_id": doc["doc_id"], "title": doc["title"], "text": doc["text"], "vec": vec})
        self.docs = built
        self.idf = idf

    def build_disk(self):
        self.actor.ensure()
        for tenant in self.tenants:
            _, response = post_json(
                self.actor.kms + "/v1/dek/for",
                {"token": self.actor.token, "tenant_id": tenant},
            )
            if not response.get("ok"):
                raise RuntimeError(response.get("error", "DEK"))
            dek = unwrap_key(self.actor.skey, b64d(response["sealed_dek"]))
            self.keys[tenant] = {
                "dek": dek,
                "key_ver": response["key_ver"],
                "wrap": response["wrap"],
            }
            path = self.store_dir / f"{tenant}.jsonl"
            with path.open("w", encoding="utf-8", newline="\n") as handle:
                idf_payload = json.dumps({"kind": "idf", "idf": self.idf}, ensure_ascii=False).encode("utf-8")
                idf_frame = seal(dek, "vector", tenant, "idf", response["key_ver"], idf_payload)
                handle.write(json.dumps({"frame": b64e(idf_frame)}, ensure_ascii=False) + "\n")
                for doc in self.docs:
                    payload = json.dumps(
                        {"doc_id": doc["doc_id"], "title": doc["title"], "text": doc["text"], "vec": doc["vec"]},
                        ensure_ascii=False,
                    ).encode("utf-8")
                    frame = seal(dek, "vector", tenant, doc["doc_id"], response["key_ver"], payload)
                    handle.write(json.dumps({"frame": b64e(frame)}, ensure_ascii=False) + "\n")
            self._reload_check(tenant, path, dek)
            backup = self.store_dir.parent / "backup"
            backup.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, backup / path.name)
        self.load_sealed(self.tenants[0])

    def _reload_check(self, tenant, path, dek):
        lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        _, plain = open_frame(dek, b64d(json.loads(lines[1])["frame"]))
        data = json.loads(plain.decode("utf-8"))
        if data["doc_id"] != self.docs[0]["doc_id"]:
            raise RuntimeError("KB_RELOAD")

    def load_sealed(self, tenant: str) -> int:
        dek = self.keys[tenant]["dek"]
        path = self.store_dir / f"{tenant}.jsonl"
        idf = None
        docs = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            _, plain = open_frame(dek, b64d(json.loads(line)["frame"]))
            item = json.loads(plain.decode("utf-8"))
            if item.get("kind") == "idf":
                idf = item["idf"]
            else:
                docs.append(item)
        if idf is None or not docs:
            raise RuntimeError("KB_SEALED")
        self.idf = idf
        self.docs = docs
        return len(docs)

    def search(self, query: str, k: int = 1):
        raw = features(query)
        qv = normalize([raw[i] * self.idf[i] for i in range(DIM)])
        scored = []
        for doc in self.docs:
            score = sum(a * b for a, b in zip(qv, doc["vec"]))
            scored.append((score, doc["doc_id"], doc))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [
            {"doc_id": doc["doc_id"], "title": doc["title"], "text": doc["text"][:80], "score": round(score, 6)}
            for score, _, doc in scored[:k]
        ]

    def open_query(self, body):
        claims, err = self.checker.require(body["token"], "infer")
        if err:
            return None, err
        try:
            dek = self.key_store.unwrap_dek(claims["tenant_id"], int(body["key_ver"]), b64d(body["wrap"]))
        except Exception as exc:
            return None, getattr(exc, "code", "WRAP_TAG")
        try:
            parsed, plain = open_frame(dek, b64d(body["query_frame"]))
        except Exception as exc:
            code = getattr(exc, "code", "TAG_FAIL")
            return None, code
        if parsed["tenant"] != claims["tenant_id"]:
            return None, "AUTHZ_DENY"
        return (claims, dek, parsed, plain.decode("utf-8")), None


def start_kb(actor, checker, corpus, store_dir, tenants, host, port, store=None, audit_log=None):
    kb = Knowledge(actor, checker, Path(corpus), Path(store_dir), tenants, store)
    kb.audit_log = audit_log
    kb.load_corpus()
    kb.build_disk()

    def health(body, query):
        return 200, {"ok": True, "docs": len(kb.docs)}

    def search(body, query):
        if not body.get("protect", True):
            passages = kb.search(body.get("query", ""))
            return 200, {"ok": True, "passages": passages}
        opened, err = kb.open_query(body)
        if err:
            return 200, {"ok": False, "error": err}
        claims, dek, parsed, text = opened
        passages = kb.search(text)
        blob = json.dumps(passages, ensure_ascii=False).encode("utf-8")
        frame = seal(dek, "retrieval", claims["tenant_id"], parsed["req_id"], parsed["key_ver"], blob)
        if kb.audit_log is not None:
            kb.audit_log.append(
                {
                    "ts": int(time.time()),
                    "node": "kb",
                    "tenant_id": claims["tenant_id"],
                    "req_id": parsed["req_id"],
                    "action": "retrieve",
                    "result": "OK",
                    "obj_type": "retrieval",
                    "key_ver": int(parsed["key_ver"]),
                    "jti": claims["jti"],
                }
            )
        return 200, {
            "ok": True,
            "retrieval_frame": b64e(frame),
            "doc_ids": [item["doc_id"] for item in passages],
        }

    def cross_open(body, query):
        claims, err = kb.checker.require(body["token"], "infer")
        if err:
            return 200, {"ok": False, "error": err}
        attacker = claims["tenant_id"]
        victim = body["victim"]
        path = kb.store_dir / f"{victim}.jsonl"
        record = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
        try:
            open_frame(kb.keys[attacker]["dek"], b64d(record["frame"]))
            return 200, {"ok": True, "opened": True}
        except Exception as exc:
            return 200, {"ok": True, "opened": False, "error": getattr(exc, "code", "TAG_FAIL")}

    kb.handle_search = search
    routes = {
        ("GET", "/v1/health"): health,
        ("POST", "/v1/search"): search,
        ("POST", "/v1/cross-open"): cross_open,
    }
    return serve(host, port, routes), kb
