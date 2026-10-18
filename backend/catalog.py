"""The objects Keepsake remembers. One physical object per category (hackathon assumption).

`category` is the text prompt given to the open-vocabulary detector (YOLO-World), so it can be any
short description of the object. Short, common words work best: "bottle" scores ~0.7 where
"water bottle" scores ~0.36 on the same photo. It also keys stored memories (object_id), so
renaming a category starts that item's memory fresh.

`min_conf` is per item: open-vocabulary scores vary a lot by prompt, and a single low cutoff lets
in false hits (e.g. "glasses"/"wallet" at ~0.2 on photos with neither). Tune these on the live camera.

Edit this list to change what Keepsake tracks; the API and frontend read it from /api/catalog.
"""
from __future__ import annotations

CATALOG: list[dict] = [
    {"category": "bottle", "name": "Water Bottle", "icon": "bottle", "min_conf": 0.55,
     "aliases": ["water bottle", "bottle", "drink", "flask"]},
    {"category": "car key", "name": "Keys", "icon": "keys", "min_conf": 0.5,
     "aliases": ["keys", "key", "car keys", "house keys", "keychain"]},
    {"category": "wallet", "name": "Wallet", "icon": "wallet", "min_conf": 0.5,
     "aliases": ["wallet", "card holder"]},
    {"category": "airpods case", "name": "AirPods", "icon": "airpods", "min_conf": 0.5,
     "aliases": ["airpods", "air pods", "earbuds", "earphones", "headphones", "airpods case"]},
    {"category": "glasses", "name": "Glasses", "icon": "glasses", "min_conf": 0.35,
     "aliases": ["glasses", "eyeglasses", "spectacles", "glasses case", "sunglasses"]},
    {"category": "backpack", "name": "Backpack", "icon": "backpack", "min_conf": 0.35,
     "aliases": ["backpack", "bag", "rucksack", "bookbag", "school bag"]},
    # Phone, mouse, laptop, cup, book, remote removed for the demo: with the trained
    # items taken out of YOLO-World's list, it kept forcing keys/wallet/AirPods into those labels.
]

for _item in CATALOG:
    _item["object_id"] = f"{_item['category'].replace(' ', '_')}_01"

BY_CATEGORY: dict[str, dict] = {c["category"]: c for c in CATALOG}
ALIASES: dict[str, list[str]] = {c["category"]: c["aliases"] for c in CATALOG}
SUPPORTED: list[str] = [c["category"] for c in CATALOG]
MIN_CONF: dict[str, float] = {c["category"]: c["min_conf"] for c in CATALOG}
