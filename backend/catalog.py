"""The objects Keepsake remembers. One physical object per category (hackathon assumption).

`category` is the text prompt given to the open-vocabulary detector (YOLO-World), so it can be any\nshort description of the object.
Edit this list to change what Keepsake tracks; the API and frontend read it from /api/catalog.
"""
from __future__ import annotations

CATALOG: list[dict] = [
    {"category": "water bottle", "name": "Water Bottle", "icon": "bottle",
     "aliases": ["water bottle", "bottle", "drink", "flask"]},
    {"category": "keys", "name": "Keys", "icon": "keys",
     "aliases": ["keys", "key", "car keys", "house keys", "keychain"]},
    {"category": "earbuds", "name": "AirPods", "icon": "airpods",
     "aliases": ["airpods", "air pods", "earbuds", "earphones", "headphones", "airpods case"]},
    {"category": "wallet", "name": "Wallet", "icon": "wallet",
     "aliases": ["wallet", "purse", "card holder"]},
    {"category": "glasses", "name": "Glasses", "icon": "glasses",
     "aliases": ["glasses", "eyeglasses", "spectacles", "glasses case", "sunglasses"]},
]

for _item in CATALOG:
    _item["object_id"] = f"{_item['category'].replace(' ', '_')}_01"

BY_CATEGORY: dict[str, dict] = {c["category"]: c for c in CATALOG}
ALIASES: dict[str, list[str]] = {c["category"]: c["aliases"] for c in CATALOG}
SUPPORTED: list[str] = [c["category"] for c in CATALOG]
