import os
import sqlite3
import threading
import time

from common.crypto import unwrap_key, wrap_key


class Store:
    def __init__(self, path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.con = sqlite3.connect(path, check_same_thread=False)
        self.con.row_factory = sqlite3.Row
        self.con.execute("PRAGMA busy_timeout=5000")
        self.lock = threading.Lock()
        self._init()

    def _init(self):
        with self.lock:
            self.con.executescript(
                """
                CREATE TABLE IF NOT EXISTS meta (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    mk BLOB NOT NULL,
                    kms_priv TEXT NOT NULL,
                    kms_pub TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS tenant (
                    tenant_id TEXT PRIMARY KEY,
                    roles TEXT NOT NULL,
                    client_pub TEXT NOT NULL,
                    salt BLOB NOT NULL
                );
                CREATE TABLE IF NOT EXISTS kek (
                    tenant_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    state TEXT NOT NULL,
                    wrapped BLOB NOT NULL,
                    PRIMARY KEY (tenant_id, version)
                );
                CREATE TABLE IF NOT EXISTS pointer (
                    tenant_id TEXT PRIMARY KEY,
                    active_version INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS revoke_jti (
                    jti TEXT PRIMARY KEY,
                    t0 REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS session (
                    sid TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    skey BLOB NOT NULL,
                    exp REAL NOT NULL
                );
                """
            )
            self.con.commit()

    def has_meta(self) -> bool:
        with self.lock:
            row = self.con.execute("SELECT mk, kms_priv, kms_pub FROM meta WHERE id=1").fetchone()
            return row is not None

    def set_meta(self, mk: bytes, kms_priv: str, kms_pub: str):
        with self.lock:
            self.con.execute(
                "INSERT INTO meta(id, mk, kms_priv, kms_pub) VALUES (1, ?, ?, ?)",
                (mk, kms_priv, kms_pub),
            )
            self.con.commit()

    def meta(self):
        with self.lock:
            row = self.con.execute("SELECT mk, kms_priv, kms_pub FROM meta WHERE id=1").fetchone()
            return bytes(row["mk"]), row["kms_priv"], row["kms_pub"]

    def enroll(self, tenant_id: str, roles: list, client_pub: str):
        mk, _, _ = self.meta()
        kek = os.urandom(16)
        salt = os.urandom(16)
        wrapped = wrap_key(mk, kek)
        with self.lock:
            self.con.execute("BEGIN IMMEDIATE")
            try:
                self.con.execute(
                    "INSERT INTO tenant(tenant_id, roles, client_pub, salt) VALUES (?,?,?,?)",
                    (tenant_id, ",".join(roles), client_pub, salt),
                )
                self.con.execute(
                    "INSERT INTO kek(tenant_id, version, state, wrapped) VALUES (?,?,?,?)",
                    (tenant_id, 1, "Active", wrapped),
                )
                self.con.execute(
                    "INSERT INTO pointer(tenant_id, active_version) VALUES (?,?)",
                    (tenant_id, 1),
                )
                self.con.commit()
            except Exception:
                self.con.rollback()
                raise

    def tenant(self, tenant_id: str):
        with self.lock:
            row = self.con.execute("SELECT * FROM tenant WHERE tenant_id=?", (tenant_id,)).fetchone()
            if row is None:
                return None
            return {
                "tenant_id": row["tenant_id"],
                "roles": row["roles"].split(",") if row["roles"] else [],
                "client_pub": row["client_pub"],
                "salt": bytes(row["salt"]),
            }

    def issue_dek(self, tenant_id: str):
        mk, _, _ = self.meta()
        with self.lock:
            pointer = self.con.execute(
                "SELECT active_version FROM pointer WHERE tenant_id=?", (tenant_id,)
            ).fetchone()
            version = int(pointer["active_version"])
            row = self.con.execute(
                "SELECT wrapped, state FROM kek WHERE tenant_id=? AND version=?",
                (tenant_id, version),
            ).fetchone()
        if row["state"] != "Active":
            raise RuntimeError("KEK_STATE")
        kek = unwrap_key(mk, bytes(row["wrapped"]))
        dek = os.urandom(16)
        return version, wrap_key(kek, dek), dek

    def unwrap_dek(self, tenant_id: str, version: int, blob: bytes) -> bytes:
        mk, _, _ = self.meta()
        with self.lock:
            row = self.con.execute(
                "SELECT wrapped, state FROM kek WHERE tenant_id=? AND version=?",
                (tenant_id, version),
            ).fetchone()
        if row is None or row["state"] in ("Retired", "Revoked"):
            raise RuntimeError("KEK_DENIED")
        kek = unwrap_key(mk, bytes(row["wrapped"]))
        return unwrap_key(kek, blob)

    def close(self):
        self.con.close()

    def rotate(self, tenant_id: str, abort=None) -> dict:
        mk, _, _ = self.meta()
        fresh = os.urandom(16)
        wrapped = wrap_key(mk, fresh)
        with self.lock:
            self.con.execute("BEGIN IMMEDIATE")
            try:
                t_begin = time.time()
                pointer = self.con.execute(
                    "SELECT active_version FROM pointer WHERE tenant_id=?", (tenant_id,)
                ).fetchone()
                old = int(pointer["active_version"])
                new = old + 1
                self.con.execute(
                    "INSERT INTO kek(tenant_id, version, state, wrapped) VALUES (?,?,?,?)",
                    (tenant_id, new, "Active", wrapped),
                )
                self.con.execute(
                    "UPDATE kek SET state='DecryptOnly' WHERE tenant_id=? AND version=? AND state='Active'",
                    (tenant_id, old),
                )
                self.con.execute(
                    "UPDATE pointer SET active_version=? WHERE tenant_id=?",
                    (new, tenant_id),
                )
                active = self.con.execute(
                    "SELECT COUNT(*) AS n FROM kek WHERE tenant_id=? AND state='Active'",
                    (tenant_id,),
                ).fetchone()["n"]
                pointer_now = self.con.execute(
                    "SELECT active_version FROM pointer WHERE tenant_id=?", (tenant_id,)
                ).fetchone()["active_version"]
                if active != 1 or int(pointer_now) != new:
                    raise RuntimeError("ROTATE_INCONSISTENT")
                if abort == "raise":
                    raise RuntimeError("ABORT_BEFORE_COMMIT")
                if abort == "kill":
                    os._exit(137)
                self.con.commit()
                t_commit = time.time()
            except Exception:
                self.con.rollback()
                raise
        return {
            "old_ver": old,
            "new_ver": new,
            "state_ok": True,
            "t_begin": t_begin,
            "t_commit": t_commit,
        }

    def status(self, tenant_id: str):
        with self.lock:
            rows = self.con.execute(
                "SELECT version, state FROM kek WHERE tenant_id=? ORDER BY version",
                (tenant_id,),
            ).fetchall()
            pointer = self.con.execute(
                "SELECT active_version FROM pointer WHERE tenant_id=?", (tenant_id,)
            ).fetchone()
        return {
            "active_version": int(pointer["active_version"]),
            "versions": [{"version": int(r["version"]), "state": r["state"]} for r in rows],
            "active_count": sum(1 for r in rows if r["state"] == "Active"),
        }

    def revoke_jti(self, jti: str, t0: float):
        with self.lock:
            self.con.execute(
                "INSERT OR REPLACE INTO revoke_jti(jti, t0) VALUES (?,?)", (jti, t0)
            )
            self.con.commit()

    def revoked(self, jti: str):
        with self.lock:
            row = self.con.execute("SELECT t0 FROM revoke_jti WHERE jti=?", (jti,)).fetchone()
            return None if row is None else float(row["t0"])

    def revoke_kek(self, tenant_id: str, version: int) -> bool:
        with self.lock:
            self.con.execute("BEGIN IMMEDIATE")
            try:
                pointer = self.con.execute(
                    "SELECT active_version FROM pointer WHERE tenant_id=?", (tenant_id,)
                ).fetchone()
                if int(pointer["active_version"]) == int(version):
                    self.con.rollback()
                    return False
                cur = self.con.execute(
                    "UPDATE kek SET state='Revoked' WHERE tenant_id=? AND version=? AND state!='Revoked'",
                    (tenant_id, version),
                )
                self.con.commit()
                return cur.rowcount == 1
            except Exception:
                self.con.rollback()
                raise

    def recover_kek(self, tenant_id: str, version: int) -> str:
        with self.lock:
            row = self.con.execute(
                "SELECT state FROM kek WHERE tenant_id=? AND version=?",
                (tenant_id, version),
            ).fetchone()
            if row is None:
                return "MISSING"
            if row["state"] == "Revoked":
                return "REVOKED_DENIED"
            if row["state"] == "Retired":
                self.con.execute(
                    "UPDATE kek SET state='DecryptOnly' WHERE tenant_id=? AND version=?",
                    (tenant_id, version),
                )
                self.con.commit()
                return "OK"
            return "NOOP"

    def retire(self, tenant_id: str, version: int):
        with self.lock:
            self.con.execute(
                "UPDATE kek SET state='Retired' WHERE tenant_id=? AND version=? AND state='DecryptOnly'",
                (tenant_id, version),
            )
            self.con.commit()

    def put_session(self, sid: str, tenant_id: str, skey: bytes, exp: float):
        with self.lock:
            self.con.execute(
                "INSERT OR REPLACE INTO session(sid, tenant_id, skey, exp) VALUES (?,?,?,?)",
                (sid, tenant_id, skey, exp),
            )
            self.con.commit()

    def session(self, sid: str):
        with self.lock:
            row = self.con.execute("SELECT * FROM session WHERE sid=?", (sid,)).fetchone()
            if row is None or float(row["exp"]) < time.time():
                return None
            return {"tenant_id": row["tenant_id"], "skey": bytes(row["skey"]), "exp": float(row["exp"])}
