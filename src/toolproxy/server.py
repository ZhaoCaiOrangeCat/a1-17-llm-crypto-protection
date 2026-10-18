import json
import secrets
import time
import urllib.parse
import urllib.request
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


def read_forecast_base(spec_path: Path) -> str:
    for line in spec_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("- url: https://api.open-meteo.com"):
            return stripped.split("url:", 1)[1].strip()
    raise RuntimeError("SPEC_BASE")


def http_get_json(url: str):
    last = None
    for _ in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "a117-tool/0.1"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            last = exc
            time.sleep(0.4)
    raise RuntimeError(f"TOOL_UPSTREAM {last}")


class WeatherTool:
    def __init__(self, actor: Actor, checker: TokenChecker, spec_path: Path, config_path: Path, store=None):
        self.actor = actor
        self.checker = checker
        self.key_store = store
        self.base = read_forecast_base(spec_path)
        self.geocode = "https://geocoding-api.open-meteo.com/v1/search"
        self.secret = secrets.token_hex(16)
        self.cache = {}
        self.live_calls = 0
        self.config_path = config_path
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self._persist_config()

    def _persist_config(self):
        self.actor.ensure()
        _, response = post_json(self.actor.kms + "/v1/dek", {"token": self.actor.token})
        if not response.get("ok"):
            raise RuntimeError(response.get("error", "DEK"))
        dek = unwrap_key(self.actor.skey, b64d(response["sealed_dek"]))
        payload = json.dumps(
            {
                "forecast_base": self.base,
                "geocode": self.geocode,
                "spec": "fixtures/tools/open-meteo-forecast.yml",
                "tool_secret": self.secret,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        frame = seal(dek, "archive", self.actor.tenant, "tool-config", response["key_ver"], payload)
        self.config_path.write_bytes(frame)
        _, plain = open_frame(dek, self.config_path.read_bytes())
        loaded = json.loads(plain.decode("utf-8"))
        self.base = loaded["forecast_base"]
        self.geocode = loaded["geocode"]
        if loaded.get("tool_secret") != self.secret:
            raise RuntimeError("TOOL_SECRET")

    def call(self, args):
        if isinstance(args, list):
            return {"calls": [self._one(item) for item in args]}
        if isinstance(args, dict) and isinstance(args.get("calls"), list):
            return {"calls": [self._one(item) for item in args["calls"]]}
        return self._one(args)

    def _one(self, args: dict) -> dict:
        latitude = args.get("latitude")
        longitude = args.get("longitude")
        name = args.get("city") or ""
        cache_key = name or f"{latitude},{longitude}"
        cached = self.cache.get(cache_key)
        if cached and time.time() - cached[0] < 3600:
            return dict(cached[1])
        if latitude is None or longitude is None:
            if not name:
                raise RuntimeError("TOOL_ARGS")
            query = urllib.parse.urlencode(
                {"name": name, "count": 1, "language": "zh", "format": "json"}
            )
            found = http_get_json(f"{self.geocode}?{query}")
            results = found.get("results") or []
            if not results:
                raise RuntimeError("TOOL_UPSTREAM")
            latitude = results[0]["latitude"]
            longitude = results[0]["longitude"]
            name = results[0].get("name") or name
        current = "temperature_2m,wind_speed_10m"
        query = urllib.parse.urlencode(
            {
                "latitude": latitude,
                "longitude": longitude,
                "current": current,
                "timezone": "Asia/Shanghai",
            }
        )
        forecast = http_get_json(f"{self.base}/v1/forecast?{query}")
        current_block = forecast.get("current") or {}
        if "temperature_2m" not in current_block:
            raise RuntimeError("TOOL_UPSTREAM")
        self.live_calls += 1
        result = {
            "place": name,
            "latitude": forecast.get("latitude"),
            "longitude": forecast.get("longitude"),
            "time": current_block.get("time"),
            "temperature_2m": current_block.get("temperature_2m"),
            "wind_speed_10m": current_block.get("wind_speed_10m"),
            "provider": "Open-Meteo",
        }
        self.cache[cache_key] = (time.time(), dict(result))
        return result


def start_tool(actor, checker, spec_path, config_path, host, port, store=None, audit_log=None):
    tool = WeatherTool(actor, checker, Path(spec_path), Path(config_path), store)
    tool.audit_log = audit_log

    def health(body, query):
        return 200, {"ok": True, "provider": "Open-Meteo"}

    def call(body, query):
        if not body.get("protect", True):
            try:
                result = tool.call(body.get("args") or {})
            except Exception as exc:
                return 200, {"ok": False, "error": str(exc)}
            return 200, {"ok": True, "result": result}
        claims, err = checker.require(body["token"], "infer")
        if err:
            return 200, {"ok": False, "error": err}
        try:
            dek = tool.key_store.unwrap_dek(claims["tenant_id"], int(body["key_ver"]), b64d(body["wrap"]))
        except Exception as exc:
            return 200, {"ok": False, "error": getattr(exc, "code", "WRAP_TAG")}
        try:
            parsed, plain = open_frame(dek, b64d(body["tool_frame"]))
        except Exception as exc:
            return 200, {"ok": False, "error": getattr(exc, "code", "TAG_FAIL")}
        args = json.loads(plain.decode("utf-8"))
        try:
            result = tool.call(args)
        except Exception as exc:
            return 200, {"ok": False, "error": str(exc)}
        blob = json.dumps(result, ensure_ascii=False).encode("utf-8")
        frame = seal(dek, "tool_result", claims["tenant_id"], parsed["req_id"], parsed["key_ver"], blob)
        if tool.audit_log is not None:
            tool.audit_log.append(
                {
                    "ts": int(time.time()),
                    "node": "tool",
                    "tenant_id": claims["tenant_id"],
                    "req_id": parsed["req_id"],
                    "action": "tool_call",
                    "result": "OK",
                    "obj_type": "tool_result",
                    "key_ver": int(parsed["key_ver"]),
                    "jti": claims["jti"],
                }
            )
        return 200, {"ok": True, "tool_frame": b64e(frame)}

    tool.handle_call = call
    routes = {
        ("GET", "/v1/health"): health,
        ("POST", "/v1/call"): call,
    }
    return serve(host, port, routes), tool
