import threading
import time

from common.crypto import sm2_decrypt, sm2_sign, sm2_verify, sm3_digest
from common.frame import canon
from common.httputil import get_json, post_json


def b64d(text: str) -> bytes:
    import base64
    return base64.b64decode(text.encode("ascii"))


class Actor:
    def __init__(self, kms: str, tenant: str, private: str, public: str):
        self.kms = kms
        self.tenant = tenant
        self.private = private
        self.public = public
        self.token = None
        self.skey = None
        self.exp = 0

    def login(self):
        _, challenge = post_json(self.kms + "/v1/challenge", {"tenant_id": self.tenant})
        if not challenge.get("ok"):
            raise RuntimeError(challenge.get("error", "CHALLENGE"))
        message = f"{challenge['challenge']}|{self.tenant}|{challenge['ts']}".encode()
        signature = sm2_sign(self.private, self.public, message)
        _, response = post_json(
            self.kms + "/v1/login",
            {
                "tenant_id": self.tenant,
                "challenge": challenge["challenge"],
                "signature": signature,
            },
        )
        if not response.get("ok"):
            raise RuntimeError(response.get("error", "LOGIN"))
        self.token = {"claims": response["claims"], "sign": response["sign"]}
        self.skey = sm2_decrypt(self.private, self.public, b64d(response["session_enc"]))
        self.exp = int(response["claims"]["exp"])

    def ensure(self):
        if self.token is None or time.time() > self.exp - 10:
            self.login()


class TokenChecker:
    def __init__(self, kms: str, kms_pub: str, store=None):
        self.kms = kms
        self.pub = kms_pub
        self.store = store
        self.cache = {}
        self.lock = threading.Lock()

    def require(self, token, role=None):
        if not token or "claims" not in token or "sign" not in token:
            return None, "AUTH_BAD_SIG"
        claims = token["claims"]
        if time.time() > int(claims["exp"]):
            return None, "AUTH_EXPIRED"
        jti = claims["jti"]
        bound = sm3_digest(canon(claims) + token["sign"].encode()).hex()
        with self.lock:
            known = self.cache.get(jti)
        if known != bound:
            if not sm2_verify(self.pub, canon(claims), token["sign"]):
                return None, "AUTH_BAD_SIG"
            with self.lock:
                self.cache[jti] = bound
        if self.store is not None:
            revoked = self.store.revoked(jti) is not None
        else:
            info = get_json(f"{self.kms}/v1/revoke/check?jti={jti}")
            revoked = bool(info.get("revoked"))
        if revoked:
            return None, "AUTH_REVOKED"
        if role and role not in claims.get("roles", []):
            return None, "AUTHZ_DENY"
        return claims, None
