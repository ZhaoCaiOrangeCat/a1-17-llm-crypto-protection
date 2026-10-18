import json
import os

from client import Terminal, wait_health, wipe
from common.actor import Actor, TokenChecker
from common.assets import verify_assets
from common.crypto import sm2_keypair, sm2_sign
from common.httputil import get_json
from kms.server import start_kms
from kms.store import Store

HOST = "127.0.0.1"
PORTS = {"kms": 8711, "gateway": 8712, "kb": 8713, "tool": 8714, "sidecar": 8715, "audit": 8716}


def boot(root: str, llama_url: str, model: str):
    manifest = verify_assets(root)
    var = os.path.join(root, "var")
    wipe(var)
    store = Store(os.path.join(var, "kms.sqlite"))
    mk = os.urandom(16)
    kms_priv, kms_pub = sm2_keypair()
    store.set_meta(mk, kms_priv, kms_pub)
    kms_base = f"http://{HOST}:{PORTS['kms']}"
    start_kms(store, HOST, PORTS["kms"])
    from audit.server import start_audit
    audit_path = os.path.join(var, "audit", "chain.jsonl")

    def sign_fn(data: bytes) -> str:
        return sm2_sign(kms_priv, kms_pub, data)

    _, audit_log = start_audit(HOST, PORTS["audit"], audit_path, kms_pub, sign_fn)
    wait_health(kms_base + "/v1/health")
    wait_health(f"http://{HOST}:{PORTS['audit']}/v1/health")

    roles = {
        "tenant-a": ["infer"],
        "tenant-b": ["infer"],
        "admin": ["key_rotate", "key_revoke", "audit_read"],
        "__kb": ["unwrap"],
        "__tool": ["unwrap"],
        "__sidecar": ["unwrap"],
    }
    keys = {}
    for tenant, role in roles.items():
        private, public = sm2_keypair()
        keys[tenant] = {"private": private, "public": public, "roles": role}
        from common.httputil import post_json
        post_json(kms_base + "/v1/enroll", {"tenant_id": tenant, "roles": role, "client_pub": public})
    os.makedirs(os.path.join(var, "keys"), exist_ok=True)
    with open(os.path.join(var, "keys", "dev.json"), "w", encoding="utf-8") as handle:
        json.dump(keys, handle)

    pub = get_json(kms_base + "/v1/pub")["public"]
    checker = TokenChecker(kms_base, pub, store)
    audit_log.checker = checker

    def actor(name):
        item = keys[name]
        made = Actor(kms_base, name, item["private"], item["public"])
        made.login()
        return made

    from kb.server import start_kb
    from toolproxy.server import start_tool
    from sidecar.server import start_sidecar
    from gateway.server import start_gateway

    _, kb_obj = start_kb(
        actor("__kb"),
        checker,
        os.path.join(root, "fixtures", "kb-corpus.jsonl"),
        os.path.join(var, "kb"),
        ["tenant-a", "tenant-b"],
        HOST,
        PORTS["kb"],
        store,
        audit_log,
    )
    _, tool_obj = start_tool(
        actor("__tool"),
        checker,
        os.path.join(root, "fixtures", "tools", "open-meteo-forecast.yml"),
        os.path.join(var, "tool", "config.bin"),
        HOST,
        PORTS["tool"],
        store,
        audit_log,
    )
    _, side_obj = start_sidecar(
        actor("__sidecar"),
        checker,
        llama_url,
        model,
        os.path.join(var, "tmp"),
        os.path.join(var, "archive"),
        HOST,
        PORTS["sidecar"],
        store,
        audit_log,
    )
    start_gateway(
        checker,
        f"http://{HOST}:{PORTS['kb']}",
        f"http://{HOST}:{PORTS['tool']}",
        f"http://{HOST}:{PORTS['sidecar']}",
        f"http://{HOST}:{PORTS['audit']}",
        HOST,
        PORTS["gateway"],
        audit_log,
        kb_obj,
        tool_obj,
        side_obj,
    )
    for name in ("kb", "tool", "sidecar", "gateway"):
        wait_health(f"http://{HOST}:{PORTS[name]}/v1/health", timeout=60)
    gateway = f"http://{HOST}:{PORTS['gateway']}"

    def terminal(name):
        item = keys[name]
        term = Terminal(kms_base, gateway, name, item["private"], item["public"])
        term.login()
        return term

    return {
        "store_path": os.path.join(var, "kms.sqlite"),
        "var": var,
        "kms": kms_base,
        "gateway": gateway,
        "audit": f"http://{HOST}:{PORTS['audit']}",
        "kb": f"http://{HOST}:{PORTS['kb']}",
        "sidecar": f"http://{HOST}:{PORTS['sidecar']}",
        "a": terminal("tenant-a"),
        "b": terminal("tenant-b"),
        "admin": terminal("admin"),
        "kb_obj": kb_obj,
        "tool_obj": tool_obj,
        "side_obj": side_obj,
        "audit_path": audit_path,
        "audit_log": audit_log,
        "kms_pub": kms_pub,
        "manifest": manifest,
    }
