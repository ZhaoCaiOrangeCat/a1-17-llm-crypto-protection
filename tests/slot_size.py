import json
import urllib.request
from pathlib import Path

path = Path(r"C:\Users\zhaoc\Desktop\a117-slots\kv.bin")
if path.exists():
    path.unlink()
req = urllib.request.Request(
    "http://127.0.0.1:18080/slots/0?action=save",
    data=json.dumps({"filename": "kv.bin"}).encode("utf-8"),
    headers={"Content-Type": "application/json"},
)
try:
    with urllib.request.urlopen(req, timeout=120) as resp:
        print("status", resp.status, resp.read()[:300])
except Exception as exc:
    print("ERR", type(exc).__name__, exc)
print("exists", path.exists(), "bytes", path.stat().st_size if path.exists() else 0)
