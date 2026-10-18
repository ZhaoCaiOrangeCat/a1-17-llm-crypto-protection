import json
import urllib.request

urls = [
    "https://zh.wikipedia.org/api/rest_v1/page/summary/SM4",
    "https://en.wikipedia.org/api/rest_v1/page/summary/SM4",
    "https://api.open-meteo.com/v1/forecast?latitude=39.9&longitude=116.4&current=temperature_2m",
    "https://geocoding-api.open-meteo.com/v1/search?name=Beijing&count=1",
    "https://restcountries.com/v3.1/alpha/cn?fields=name,capital",
    "https://api.frankfurter.app/latest?from=USD&to=CNY",
    "https://raw.githubusercontent.com/open-meteo/open-meteo/main/openapi.yml",
]
for u in urls:
    try:
        req = urllib.request.Request(u, headers={"User-Agent": "a117-probe/0.1"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = resp.read(180)
            print("OK", resp.status, u, body[:80])
    except Exception as e:
        print("FAIL", type(e).__name__, u, str(e)[:160])
