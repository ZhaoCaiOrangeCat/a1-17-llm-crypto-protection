import json
import urllib.request

req = urllib.request.Request(
    "https://api.github.com/repos/open-meteo/open-meteo/git/trees/main?recursive=1",
    headers={"User-Agent": "a117", "Accept": "application/vnd.github+json"},
)
with urllib.request.urlopen(req, timeout=60) as resp:
    data = json.loads(resp.read().decode())
print("truncated", data.get("truncated"), "n", len(data.get("tree", [])))
paths = [t["path"] for t in data["tree"]]
for p in paths:
    low = p.lower()
    if "open" in low or p.endswith(".md") or "doc" in low:
        if p.count("/") <= 2:
            print(p)
