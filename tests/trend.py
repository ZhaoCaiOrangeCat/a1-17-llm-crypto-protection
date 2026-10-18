import json

rows = [json.loads(line) for line in open(r"C:\Users\zhaoc\Desktop\密码\data\raw\m5.jsonl", encoding="utf-8")]
pairs = []
index = 0
while index < len(rows) - 1:
    off = rows[index]
    on = rows[index + 1]
    pairs.append((off["latency_ms"], on["latency_ms"], on["latency_ms"] - off["latency_ms"], off["t_start"]))
    index += 2
print("pairs", len(pairs))
start = pairs[0][3]
for begin in range(0, len(pairs), 50):
    chunk = pairs[begin:begin + 50]
    offs = [item[0] for item in chunk]
    deltas = [item[2] for item in chunk]
    qualified = sum(1 for off, _, delta, _ in chunk if delta <= 30 or delta <= 0.15 * off)
    minute = (chunk[-1][3] - start) / 60
    print(
        f"{begin:4d} n={len(chunk):2d} off={sum(offs)/len(offs):7.1f} on={sum(item[1] for item in chunk)/len(chunk):7.1f} "
        f"delta={sum(deltas)/len(deltas):6.1f} qual={qualified:2d} t={minute:5.1f}m"
    )
