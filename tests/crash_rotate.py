import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from kms.store import Store

store = Store(sys.argv[1])
store.rotate(sys.argv[2], abort="kill")
