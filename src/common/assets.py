import hashlib
import json
from pathlib import Path


def verify_assets(root) -> dict:
    root = Path(root)
    manifest_path = root / "fixtures" / "assets.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for item in manifest["files"]:
        path = root / item["path"]
        blob = path.read_bytes()
        digest = hashlib.sha256(blob).hexdigest()
        if digest != item["sha256"] or len(blob) != int(item["bytes"]):
            raise RuntimeError(f"ASSET {item['path']}")
    return manifest
