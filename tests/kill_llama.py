import subprocess
out = subprocess.check_output(["netstat", "-ano"], text=True, errors="replace")
for line in out.splitlines():
    if ":18080" in line and "LISTENING" in line:
        print(line)
        pid = line.split()[-1]
        subprocess.check_call(["taskkill", "/PID", pid, "/F"])
        print("killed", pid)
