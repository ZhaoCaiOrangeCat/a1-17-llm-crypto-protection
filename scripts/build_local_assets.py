import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    corpus_path = ROOT / "fixtures" / "kb-corpus.jsonl"
    docs = [json.loads(line) for line in corpus_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    titles = [doc["title"] for doc in docs]
    for left in titles:
        for right in titles:
            if left != right and left in right:
                print("title-substring", left, right)
    templates = [
        "请用五句话说明{title}，每句不少于三十字。",
        "请用五句话说明资料中的{title}，每句不少于三十字。",
        "请依据资料，用五句话概括{title}，每句不少于三十字。",
        "请用五句话写出{title}在资料里的内容，每句不少于三十字。",
    ]
    rows = []
    index = 0
    while len(rows) < 1000:
        doc = docs[index % len(docs)]
        template = templates[(index // len(docs)) % len(templates)]
        rows.append(
            {
                "doc_id": doc["doc_id"],
                "title": doc["title"],
                "prompt": template.format(title=doc["title"]),
            }
        )
        index += 1
    prompt_path = ROOT / "fixtures" / "prompts-1000.jsonl"
    with prompt_path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    files = [
        "fixtures/kb-corpus.jsonl",
        "fixtures/prompts-1000.jsonl",
        "fixtures/tools/open-meteo-forecast.yml",
        "fixtures/tools/get_weather.json",
    ]
    listed = []
    for rel in files:
        blob = (ROOT / rel).read_bytes()
        listed.append({"path": rel, "bytes": len(blob), "sha256": hashlib.sha256(blob).hexdigest()})
    manifest = {
        "note": "本地实验资产。指标运行只读取这些文件，不在运行时下载。",
        "kb": {
            "path": "fixtures/kb-corpus.jsonl",
            "source": "https://raw.githubusercontent.com/ymcui/cmrc2018/master/squad-style-data/cmrc2018_trial.json",
            "docs": len(docs),
            "license": "CMRC 2018 trial passages, research use",
        },
        "tool": {
            "path": "fixtures/tools/open-meteo-forecast.yml",
            "manifest": "fixtures/tools/get_weather.json",
            "source": "https://raw.githubusercontent.com/open-meteo/open-meteo/main/openapi/forecast.yml",
            "provider": "Open-Meteo",
            "forecast": "https://api.open-meteo.com/v1/forecast",
        },
        "prompts": "fixtures/prompts-1000.jsonl",
        "files": listed,
    }
    (ROOT / "fixtures" / "assets.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"docs={len(docs)} prompts={len(rows)}")


if __name__ == "__main__":
    main()
