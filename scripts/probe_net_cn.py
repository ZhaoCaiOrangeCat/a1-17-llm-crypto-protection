import urllib.request

urls = [
    "https://hf-mirror.com",
    "https://modelscope.cn",
    "https://gitee.com",
    "https://geo.datav.aliyun.com/areas_v3/bound/110000.json",
    "https://suggestion.baidu.com/su?wd=%E5%95%86%E5%AF%86&p=3",
    "https://api.github.com/repos/open-meteo/open-meteo",
    "https://cdn.jsdelivr.net/gh/open-meteo/open-meteo@main/openapi.yml",
    "https://raw.gitmirror.com/open-meteo/open-meteo/main/openapi.yml",
]
for u in urls:
    try:
        req = urllib.request.Request(u, headers={"User-Agent": "a117-probe/0.1"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            body = resp.read(120)
            print("OK", resp.status, len(body), u[:90], body[:60])
    except Exception as e:
        print("FAIL", type(e).__name__, u[:90], str(e)[:120])
