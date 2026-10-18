import hashlib
import hmac
import os
import secrets
import threading

from gmssl import func, sm2, sm3
from gmssl.sm4 import CryptSM4, SM4_ENCRYPT

_SM3_ABC = "66c7f0f462eeedd9d1f2d46bdc10e4e24167c4875cf2f7a2297da02b8f4ba8e0"
_sched = {}
_sched_lock = threading.Lock()


class CryptoError(Exception):
    def __init__(self, code, detail=""):
        super().__init__(code if not detail else f"{code}: {detail}")
        self.code = code


def sm3_digest(data: bytes) -> bytes:
    return bytes.fromhex(sm3.sm3_hash(list(data)))


def hmac_sm3(key: bytes, msg: bytes) -> bytes:
    block = 64
    if len(key) > block:
        key = sm3_digest(key)
    key = key.ljust(block, b"\x00")
    ipad = bytes(b ^ 0x36 for b in key)
    opad = bytes(b ^ 0x5C for b in key)
    return sm3_digest(opad + sm3_digest(ipad + msg))


def kdf(secret: bytes, info: bytes, n: int = 16) -> bytes:
    out = b""
    counter = 1
    while len(out) < n:
        out += sm3_digest(secret + info + counter.to_bytes(4, "big"))
        counter += 1
    return out[:n]


def _cipher(key: bytes) -> CryptSM4:
    with _sched_lock:
        found = _sched.get(key)
        if found is None:
            found = CryptSM4()
            found.set_key(key, SM4_ENCRYPT)
            _sched[key] = found
        return found


def sm4_block(key: bytes, block: bytes) -> bytes:
    if len(key) != 16 or len(block) != 16:
        raise CryptoError("SM4_LEN")
    cipher = _cipher(key)
    return bytes(cipher.one_round(cipher.sk, list(block)))


def sm4_ctr(key: bytes, nonce: bytes, data: bytes) -> bytes:
    if len(nonce) != 16:
        raise CryptoError("NONCE_LEN")
    counter = int.from_bytes(nonce, "big")
    out = bytearray()
    offset = 0
    while offset < len(data):
        stream = sm4_block(key, counter.to_bytes(16, "big"))
        take = min(16, len(data) - offset)
        chunk = data[offset:offset + take]
        out.extend(left ^ right for left, right in zip(chunk, stream))
        counter = (counter + 1) & ((1 << 128) - 1)
        offset += take
    return bytes(out)


def wrap_key(parent: bytes, child: bytes) -> bytes:
    if len(child) != 16:
        raise CryptoError("KEY_LEN")
    nonce = os.urandom(16)
    ct = sm4_ctr(kdf(parent, b"wrap-enc"), nonce, child)
    tag = hmac_sm3(kdf(parent, b"wrap-mac"), nonce + ct)
    return nonce + ct + tag


def unwrap_key(parent: bytes, blob: bytes) -> bytes:
    if len(blob) != 64:
        raise CryptoError("WRAP_LEN")
    nonce, ct, tag = blob[:16], blob[16:32], blob[32:]
    expect = hmac_sm3(kdf(parent, b"wrap-mac"), nonce + ct)
    if not hmac.compare_digest(expect, tag):
        raise CryptoError("WRAP_TAG")
    return sm4_ctr(kdf(parent, b"wrap-enc"), nonce, ct)


def _curve_n() -> int:
    return int(sm2.default_ecc_table["n"], 16)


def sm2_keypair() -> tuple[str, str]:
    order = _curve_n()
    secret = secrets.randbelow(order - 1) + 1
    private = f"{secret:064x}"
    holder = sm2.CryptSM2(private_key=private, public_key="")
    public = holder._kg(secret, holder.ecc_table["g"])
    if not public:
        raise CryptoError("SM2_KEY")
    return private, public


def sm2_sign(private: str, public: str, data: bytes) -> str:
    order = _curve_n()
    holder = sm2.CryptSM2(private_key=private, public_key=public)
    for _ in range(8):
        k = secrets.randbelow(order - 1) + 1
        signature = holder.sign_with_sm3(data, f"{k:064x}")
        if signature:
            return signature
    raise CryptoError("SM2_SIGN")


def sm2_verify(public: str, data: bytes, signature: str) -> bool:
    holder = sm2.CryptSM2(private_key="", public_key=public)
    try:
        return bool(holder.verify_with_sm3(signature, data))
    except Exception:
        return False


def sm2_encrypt(public: str, data: bytes) -> bytes:
    holder = sm2.CryptSM2(private_key="", public_key=public)
    encrypted = holder.encrypt(data)
    if not encrypted:
        raise CryptoError("SM2_ENC")
    return encrypted


def sm2_decrypt(private: str, public: str, data: bytes) -> bytes:
    holder = sm2.CryptSM2(private_key=private, public_key=public)
    plain = holder.decrypt(data)
    if not plain:
        raise CryptoError("SM2_DEC")
    return plain


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def self_check() -> None:
    if sm3_digest(b"abc").hex() != _SM3_ABC:
        raise CryptoError("SM3_KAT")
    key = os.urandom(16)
    nonce = os.urandom(16)
    plain = "密码保护".encode() * 20
    ct = sm4_ctr(key, nonce, plain)
    if sm4_ctr(key, nonce, ct) != plain:
        raise CryptoError("SM4_KAT")
    parent = os.urandom(16)
    child = os.urandom(16)
    blob = wrap_key(parent, child)
    if unwrap_key(parent, blob) != child:
        raise CryptoError("WRAP_KAT")
    private, public = sm2_keypair()
    message = b"a117-sm2"
    signature = sm2_sign(private, public, message)
    if not sm2_verify(public, message, signature):
        raise CryptoError("SM2_KAT")
    sealed = sm2_encrypt(public, child)
    if sm2_decrypt(private, public, sealed) != child:
        raise CryptoError("SM2_ENC_KAT")
