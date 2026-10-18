"""Download a small real corpus and a real tool definition."""
import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "fixtures"
FIX.mkdir(parents=True, exist_ok=True)
UA = {"User-Agent": "a117-fetch/0.1", "Accept": "application/vnd.github+json"}


def get(url, timeout=60):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def main():
    listing = json.loads(
        get("https://api.github.com/repos/ymcui/cmrc2018/contents/squad-style-data").decode()
    )
    names = [item["name"] for item in listing]
    print("cmrc files", names)
    prefer = None
    for name in ("cmrc2018_trial.json", "cmrc2018_dev.json", "cmrc2018_train.json"):
        if name in names:
            prefer = name
            break
    if prefer is None:
        raise SystemExit("cmrc json not found")
    raw_url = f"https://raw.githubusercontent.com/ymcui/cmrc2018/master/squad-style-data/{prefer}"
    print("download", raw_url)
    payload = json.loads(get(raw_url).decode("utf-8"))
    docs = []
    for article in payload["data"]:
        title = article.get("title") or ""
        for para in article.get("paragraphs") or []:
            text = (para.get("context") or "").strip()
            if len(text) < 40:
                continue
            docs.append(
                {
                    "doc_id": f"cmrc-{len(docs)+1:04d}",
                    "title": title,
                    "text": text[:480],
                    "source": raw_url,
                    "license": "CMRC 2018 dataset, research use; passages are the original contexts",
                }
            )
            if len(docs) >= 24:
                break
        if len(docs) >= 24:
            break
    out = FIX / "kb-corpus.jsonl"
    with out.open("w", encoding="utf-8", newline="\n") as f:
        for doc in docs:
            f.write(json.dumps(doc, ensure_ascii=False) + "\n")
    print("kb", out, "docs", len(docs), "src", prefer)

    tree = json.loads(
        get("https://api.github.com/repos/open-meteo/open-meteo/git/trees/main?recursive=1").decode()
    )
    paths = [t["path"] for t in tree.get("tree", []) if t["path"].lower().endswith(("openapi.yml", "openapi.yaml", "openapi.json"))]
    print("openapi candidates", paths[:12], "count", len(paths))
    spec_url = None
    for path in paths:
        if path.count("/") <= 2:
            spec_url = "https://raw.githubusercontent.com/open-meteo/open-meteo/main/" + path
            break
    if spec_url is None and paths:
        spec_url = "https://raw.githubusercontent.com/open-meteo/open-meteo/main/" + paths[0]
    tool_dir = FIX / "tools"
    tool_dir.mkdir(parents=True, exist_ok=True)
    if spec_url:
        print("download", spec_url)
        blob = get(spec_url, timeout=90)
        spec_path = tool_dir / "open-meteo-openapi.txt"
        spec_path.write_bytes(blob)
        print("spec bytes", len(blob))
    else:
        spec_path = None
        print("openapi file not in repo tree")
    manifest = {
        "name": "get_weather",
        "provider": "Open-Meteo",
        "spec_file": str(spec_path.relative_to(ROOT)).replace("\\", "/") if spec_path else None,
        "geocoding": "https://geocoding-api.open-meteo.com/v1/search",
        "forecast": "https://api.open-meteo.com/v1/forecast",
        "docs": "https://open-meteo.com/en/docs",
        "auth": "none for non-commercial endpoint",
        "parameters": {
            "city": "string, required, passed to geocoding search",
        },
    }
    (tool_dir / "get_weather.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("tool manifest written")


if __name__ == "__main__":
    main()
