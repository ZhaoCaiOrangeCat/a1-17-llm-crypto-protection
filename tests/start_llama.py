import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_m1_m11 import ensure_llama

print(ensure_llama(), flush=True)
