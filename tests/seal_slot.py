import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from common.frame import open_frame, seal

src = Path(r"C:\Users\zhaoc\Desktop\a117-slots\kv.bin")
dst = Path(r"C:\Users\zhaoc\Desktop\a117-slots\kv-sealed.bin")
dek = b"0123456789abcdef"
total = src.stat().st_size
print("bytes", total, flush=True)
started = time.time()
first = b""
count = 0
with src.open("rb") as inp, dst.open("wb") as out:
    while True:
        piece = inp.read(256 * 1024)
        if not piece:
            break
        if count == 0:
            first = piece
        frame = seal(dek, "kv_block", "tenant-a", f"slot-{count}", 1, piece)
        out.write(len(frame).to_bytes(4, "big") + frame)
        count += 1
        if count % 10 == 0:
            print("chunk", count, "sec", round(time.time() - started, 1), flush=True)
print("done", count, "sec", round(time.time() - started, 1), "out", dst.stat().st_size, flush=True)
with dst.open("rb") as handle:
    size = int.from_bytes(handle.read(4), "big")
    frame = handle.read(size)
_, plain = open_frame(dek, frame)
print("restored", plain == first, flush=True)
src.unlink()
print("plain_gone", not src.exists(), flush=True)
