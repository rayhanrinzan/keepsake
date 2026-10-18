"""Try the surroundings sentence on each item's newest saved photo, without the camera running.

    cd backend && ../.venv/bin/python ../scripts/try_describe.py

Sends those photos to xAI (needs XAI_API_KEY in the repo .env). Prints one line per item.
"""
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(HERE))

from voice import load_env_file  # noqa: E402

load_env_file(HERE.parent / ".env")
os.environ.setdefault("CTRLF_DESCRIBE", "1")

from catalog import CATALOG  # noqa: E402
from database import Database  # noqa: E402
from describe import SceneDescriber, enabled  # noqa: E402

if not enabled():
    sys.exit("Describe is off: set XAI_API_KEY in .env (and don't set CTRLF_DESCRIBE=0).")
db = Database(os.getenv("CTRLF_DB_PATH", str(HERE / "data" / "ctrlf.db")))
snap_dir = Path(os.getenv("CTRLF_SNAPSHOT_DIR", str(HERE / "data" / "snapshots")))
d = SceneDescriber()
print("model:", os.getenv("CTRLF_VISION_MODEL", "grok-4.7"))
for item in CATALOG:
    snaps = db.get_snapshots(item["object_id"], limit=1)
    s = snaps[0] if snaps else None
    if not s:
        print(f"{item['name']}: no photo yet")
        continue
    t = time.time()
    text = d.describe(s["id"], snap_dir / s["filename"], item["name"].lower(), (s["x0"], s["y0"], s["x1"], s["y1"]))
    print(f"{item['name']} ({time.time() - t:.1f}s): {text or '(no sentence: see warnings above)'}")
