import subprocess
from pathlib import Path
out = Path(r"C:\Users\zhaoc\Desktop\密码\data\logs\llama-help.txt")
out.parent.mkdir(parents=True, exist_ok=True)
proc = subprocess.run(
    [r"E:\qwen agent\llama-server.exe", "--help"],
    cwd=r"E:\qwen agent",
    capture_output=True,
    text=True,
    encoding="utf-8",
    errors="replace",
)
out.write_text((proc.stdout or "") + "\n" + (proc.stderr or ""), encoding="utf-8")
print("code", proc.returncode, "bytes", out.stat().st_size)
