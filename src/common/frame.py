import json
import time

from common.crypto import CryptoError, hmac_sm3, kdf, sm4_ctr

OBJ = {
    "prompt": 1,
    "query": 2,
    "retrieval": 3,
    "vector": 4,
    "output": 5,
    "tool_arg": 6,
    "tool_result": 7,
    "kv_block": 8,
    "audit": 9,
    "archive": 10,
}
OBJ_NAME = {value: key for key, value in OBJ.items()}


def canon(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _aad(version, obj, key_ver, ts, tenant, req_id, nonce) -> bytes:
    return b"|".join(
        [
            str(version).encode(),
            str(obj).encode(),
            str(key_ver).encode(),
            str(ts).encode(),
            tenant.encode(),
            req_id.encode(),
            nonce,
        ]
    )


def encode_frame(obj_name, tenant, req_id, key_ver, ts, nonce, ct, mac) -> bytes:
    tenant_b = tenant.encode()
    req_b = req_id.encode()
    return b"".join(
        [
            b"A117",
            bytes([1, OBJ[obj_name]]),
            int(key_ver).to_bytes(4, "big"),
            int(ts).to_bytes(8, "big"),
            len(tenant_b).to_bytes(2, "big"),
            tenant_b,
            len(req_b).to_bytes(2, "big"),
            req_b,
            nonce,
            len(ct).to_bytes(4, "big"),
            ct,
            mac,
        ]
    )


def parse_frame(blob: bytes) -> dict:
    try:
        if len(blob) < 4 or blob[:4] != b"A117":
            raise CryptoError("FRAME")
        off = 4
        version = blob[off]
        obj = blob[off + 1]
        off += 2
        key_ver = int.from_bytes(blob[off:off + 4], "big")
        off += 4
        ts = int.from_bytes(blob[off:off + 8], "big")
        off += 8
        tlen = int.from_bytes(blob[off:off + 2], "big")
        off += 2
        tenant = blob[off:off + tlen].decode("utf-8")
        off += tlen
        rlen = int.from_bytes(blob[off:off + 2], "big")
        off += 2
        req_id = blob[off:off + rlen].decode("utf-8")
        off += rlen
        nonce = blob[off:off + 16]
        off += 16
        clen = int.from_bytes(blob[off:off + 4], "big")
        off += 4
        ct = blob[off:off + clen]
        off += clen
        mac = blob[off:off + 32]
        off += 32
        if off != len(blob) or version != 1 or obj not in OBJ_NAME:
            raise CryptoError("FRAME")
    except CryptoError:
        raise
    except Exception as exc:
        raise CryptoError("FRAME") from exc
    return {
        "version": version,
        "obj": obj,
        "obj_name": OBJ_NAME[obj],
        "key_ver": key_ver,
        "ts": ts,
        "tenant": tenant,
        "req_id": req_id,
        "nonce": nonce,
        "ct": ct,
        "mac": mac,
    }


def seal(dek: bytes, obj_name: str, tenant: str, req_id: str, key_ver: int, plaintext: bytes) -> bytes:
    nonce = os_nonce()
    ts = int(time.time())
    obj = OBJ[obj_name]
    ct = sm4_ctr(kdf(dek, b"enc" + bytes([obj])), nonce, plaintext)
    aad = _aad(1, obj, key_ver, ts, tenant, req_id, nonce)
    mac = hmac_sm3(kdf(dek, b"mac" + bytes([obj])), aad + ct)
    return encode_frame(obj_name, tenant, req_id, key_ver, ts, nonce, ct, mac)


def os_nonce() -> bytes:
    import os
    return os.urandom(16)


def open_frame(dek: bytes, blob: bytes) -> tuple[dict, bytes]:
    parsed = parse_frame(blob)
    aad = _aad(
        parsed["version"],
        parsed["obj"],
        parsed["key_ver"],
        parsed["ts"],
        parsed["tenant"],
        parsed["req_id"],
        parsed["nonce"],
    )
    mac_key = kdf(dek, b"mac" + bytes([parsed["obj"]]))
    expect = hmac_sm3(mac_key, aad + parsed["ct"])
    import hmac as hmac_mod
    if not hmac_mod.compare_digest(expect, parsed["mac"]):
        raise CryptoError("TAG_FAIL")
    plain = sm4_ctr(kdf(dek, b"enc" + bytes([parsed["obj"]])), parsed["nonce"], parsed["ct"])
    return parsed, plain
