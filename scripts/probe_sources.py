import json
import urllib.request

urls = [
    "https://api.github.com/repos/ymcui/cmrc2018/contents/squad-style-data",
    "https://api.github.com/repos/open-meteo/open-meteo/contents/",
    "https://raw.githubusercontent.com/ymcui/cmrc2018/master/README.md",
    "https://api.open-meteo.com/v1/forecast?latitude=39.9&longitude=116.4&current=temperature_2m",
    "https://www.chinamoney.com.cn/r/cms/www/chinamoney/data/fx/rfx-sp-quot.json",
    "https://modelscope.cn/api/v1/datasets?PageSize=5&PageNumber=1&Query=cmrc",
]
for u in urls:
    try:
        req = urllib.request.Request(
            u,
            headers={
                "User-Agent": "a117-probe/0.1",
                "Accept": "application/vnd.github+json",
            },
        )
        with urllib.request.urlopen(req, timeout=12) as resp:
            body = resp.read(400)
            print("OK", resp.status, u[:100])
            print(body[:220].decode("utf-8", "replace").replace("\n", " ")[:220])
            print("---")
    except Exception as e:
        print("FAIL", type(e).__name__, u[:100], str(e)[:160])
        print("---")
