import base64
import secrets
import threading
import time

from common.crypto import CryptoError, sm2_encrypt, sm2_sign, sm2_verify, sm3_digest, wrap_key
from common.frame import canon
from common.httputil import serve

USER_TTL = 60
SERVICE_TTL = 3600


def b64e(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def b64d(text: str) -> bytes:
    return base64.b64decode(text.encode("ascii"))


class KmsApp:
    def __init__(self, store):
        self.store = store
        self.challenges = {}
        self.verified = {}
        self.verified_lock = threading.Lock()

    def routes(self):
        return {
            ("GET", "/v1/health"): self.health,
            ("GET", "/v1/pub"): self.pub,
            ("POST", "/v1/enroll"): self.enroll,
            ("POST", "/v1/challenge"): self.challenge,
            ("POST", "/v1/login"): self.login,
            ("POST", "/v1/dek"): self.dek,
            ("POST", "/v1/dek/for"): self.dek_for,
            ("POST", "/v1/unwrap"): self.unwrap,
            ("POST", "/v1/rotate"): self.rotate,
            ("POST", "/v1/revoke"): self.revoke,
            ("GET", "/v1/revoke/check"): self.revoke_check,
            ("POST", "/v1/status"): self.status,
            ("POST", "/v1/kek/revoke"): self.kek_revoke,
            ("POST", "/v1/kek/recover"): self.kek_recover,
            ("POST", "/v1/kek/retire"): self.kek_retire,
            ("POST", "/v1/salt"): self.salt,
        }

    def health(self, body, query):
        return 200, {"ok": True}

    def pub(self, body, query):
        _, _, public = self.store.meta()
        return 200, {"ok": True, "public": public}

    def enroll(self, body, query):
        self.store.enroll(body["tenant_id"], body["roles"], body["client_pub"])
        return 200, {"ok": True}

    def challenge(self, body, query):
        tenant = self.store.tenant(body["tenant_id"])
        if tenant is None:
            return 200, {"ok": False, "error": "NO_TENANT"}
        nonce = secrets.token_hex(16)
        ts = int(time.time())
        self.challenges[body["tenant_id"]] = (nonce, ts)
        return 200, {"ok": True, "challenge": nonce, "ts": ts}

    def login(self, body, query):
        tenant_id = body["tenant_id"]
        stored = self.challenges.pop(tenant_id, None)
        if stored is None or stored[0] != body.get("challenge"):
            return 200, {"ok": False, "error": "AUTH_BAD_SIG"}
        if abs(int(time.time()) - stored[1]) > 60:
            return 200, {"ok": False, "error": "WINDOW"}
        tenant = self.store.tenant(tenant_id)
        message = f"{stored[0]}|{tenant_id}|{stored[1]}".encode()
        if not sm2_verify(tenant["client_pub"], message, body.get("signature", "")):
            return 200, {"ok": False, "error": "AUTH_BAD_SIG"}
        ttl = SERVICE_TTL if tenant_id.startswith("__") else USER_TTL
        now = int(time.time())
        session_key = os_urandom()
        sid = secrets.token_hex(8)
        claims = {
            "tenant_id": tenant_id,
            "sub": tenant_id,
            "roles": tenant["roles"],
            "iat": now,
            "exp": now + ttl,
            "jti": secrets.token_hex(8),
            "sid": sid,
        }
        _, priv, pub = self.store.meta()
        signature = sm2_sign(priv, pub, canon(claims))
        self.store.put_session(sid, tenant_id, session_key, claims["exp"])
        sealed = sm2_encrypt(tenant["client_pub"], session_key)
        return 200, {
            "ok": True,
            "claims": claims,
            "sign": signature,
            "session_enc": b64e(sealed),
        }

    def _token_claims(self, token):
        claims = token["claims"]
        _, _, pub = self.store.meta()
        if int(time.time()) > int(claims["exp"]):
            raise CryptoError("AUTH_EXPIRED")
        jti = claims["jti"]
        bound = sm3_digest(canon(claims) + token["sign"].encode()).hex()
        with self.verified_lock:
            known = self.verified.get(jti)
        if known != bound:
            if not sm2_verify(pub, canon(claims), token["sign"]):
                raise CryptoError("AUTH_BAD_SIG")
            with self.verified_lock:
                self.verified[jti] = bound
        if self.store.revoked(claims["jti"]) is not None:
            raise CryptoError("AUTH_REVOKED")
        return claims

    def dek(self, body, query):
        try:
            claims = self._token_claims(body["token"])
        except CryptoError as exc:
            return 200, {"ok": False, "error": exc.code}
        session = self.store.session(claims["sid"])
        if session is None:
            return 200, {"ok": False, "error": "AUTH_EXPIRED"}
        version, wrapped, dek = self.store.issue_dek(claims["tenant_id"])
        return 200, {
            "ok": True,
            "key_ver": version,
            "wrap": b64e(wrapped),
            "sealed_dek": b64e(wrap_key(session["skey"], dek)),
        }

    def dek_for(self, body, query):
        try:
            claims = self._token_claims(body["token"])
        except CryptoError as exc:
            return 200, {"ok": False, "error": exc.code}
        if "unwrap" not in claims["roles"]:
            return 200, {"ok": False, "error": "AUTHZ_DENY"}
        session = self.store.session(claims["sid"])
        if session is None:
            return 200, {"ok": False, "error": "AUTH_EXPIRED"}
        version, wrapped, dek = self.store.issue_dek(body["tenant_id"])
        return 200, {
            "ok": True,
            "key_ver": version,
            "wrap": b64e(wrapped),
            "sealed_dek": b64e(wrap_key(session["skey"], dek)),
        }

    def unwrap(self, body, query):
        try:
            claims = self._token_claims(body["token"])
        except CryptoError as exc:
            return 200, {"ok": False, "error": exc.code}
        if "unwrap" not in claims["roles"]:
            return 200, {"ok": False, "error": "AUTHZ_DENY"}
        session = self.store.session(claims["sid"])
        if session is None:
            return 200, {"ok": False, "error": "AUTH_EXPIRED"}
        try:
            dek = self.store.unwrap_dek(body["tenant_id"], int(body["key_ver"]), b64d(body["wrap"]))
        except Exception as exc:
            code = "KEK_DENIED" if "KEK" in str(exc) else "WRAP_TAG"
            return 200, {"ok": False, "error": code}
        return 200, {"ok": True, "sealed_dek": b64e(wrap_key(session["skey"], dek))}

    def rotate(self, body, query):
        try:
            claims = self._token_claims(body["token"])
        except CryptoError as exc:
            return 200, {"ok": False, "error": exc.code}
        if "key_rotate" not in claims["roles"]:
            return 200, {"ok": False, "error": "AUTHZ_DENY"}
        result = self.store.rotate(body["tenant_id"])
        return 200, {"ok": True, **result}

    def revoke(self, body, query):
        try:
            claims = self._token_claims(body["token"])
        except CryptoError as exc:
            return 200, {"ok": False, "error": exc.code}
        if "key_revoke" not in claims["roles"]:
            return 200, {"ok": False, "error": "AUTHZ_DENY"}
        t0 = time.time()
        self.store.revoke_jti(body["jti"], t0)
        return 200, {"ok": True, "t0": t0}

    def revoke_check(self, body, query):
        jti = ""
        for part in query.split("&"):
            if part.startswith("jti="):
                jti = part.split("=", 1)[1]
        t0 = self.store.revoked(jti)
        return 200, {"ok": True, "revoked": t0 is not None, "t0": t0}

    def status(self, body, query):
        try:
            claims = self._token_claims(body["token"])
        except CryptoError as exc:
            return 200, {"ok": False, "error": exc.code}
        if "key_rotate" not in claims["roles"] and claims["tenant_id"] != body["tenant_id"]:
            return 200, {"ok": False, "error": "AUTHZ_DENY"}
        return 200, {"ok": True, **self.store.status(body["tenant_id"])}

    def kek_revoke(self, body, query):
        try:
            claims = self._token_claims(body["token"])
        except CryptoError as exc:
            return 200, {"ok": False, "error": exc.code}
        if "key_revoke" not in claims["roles"]:
            return 200, {"ok": False, "error": "AUTHZ_DENY"}
        done = self.store.revoke_kek(body["tenant_id"], int(body["version"]))
        return 200, {"ok": done, "error": "" if done else "KEK_DENIED"}

    def kek_recover(self, body, query):
        try:
            claims = self._token_claims(body["token"])
        except CryptoError as exc:
            return 200, {"ok": False, "error": exc.code}
        if "key_rotate" not in claims["roles"]:
            return 200, {"ok": False, "error": "AUTHZ_DENY"}
        result = self.store.recover_kek(body["tenant_id"], int(body["version"]))
        return 200, {"ok": result == "OK", "result": result}

    def kek_retire(self, body, query):
        try:
            claims = self._token_claims(body["token"])
        except CryptoError as exc:
            return 200, {"ok": False, "error": exc.code}
        if "key_rotate" not in claims["roles"]:
            return 200, {"ok": False, "error": "AUTHZ_DENY"}
        self.store.retire(body["tenant_id"], int(body["version"]))
        return 200, {"ok": True}

    def salt(self, body, query):
        try:
            claims = self._token_claims(body["token"])
        except CryptoError as exc:
            return 200, {"ok": False, "error": exc.code}
        if "unwrap" not in claims["roles"]:
            return 200, {"ok": False, "error": "AUTHZ_DENY"}
        tenant = self.store.tenant(body["tenant_id"])
        return 200, {"ok": True, "salt": b64e(tenant["salt"])}


def os_urandom():
    import os
    return os.urandom(16)


def start_kms(store, host, port):
    app = KmsApp(store)
    return serve(host, port, app.routes()), app
