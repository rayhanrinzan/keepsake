"""The objects Keepsake remembers. One physical object per category (hackathon assumption).

`category` is the class name in our trained model (models/items.pt, made by last-seen/train.py).
`prompt` is the text used instead when falling back to YOLO-World (no items.pt yet).
Edit this list to change what Keepsake tracks; the API and frontend read it from /api/catalog.
"""
from __future__ import annotations

CATALOG: list[dict] = [
    {"category": "glasses_case", "prompt": "glasses case", "name": "Glasses", "icon": "glasses",
     "aliases": ["glasses", "eyeglasses", "spectacles", "glasses case", "reading glasses"]},
    {"category": "keys", "prompt": "car key", "name": "Keys", "icon": "keys",
     "aliases": ["keys", "key", "car keys", "house keys", "keychain"]},
    {"category": "wallet", "prompt": "leather wallet", "name": "Wallet", "icon": "wallet",
     "aliases": ["wallet", "purse", "card holder"]},
    {"category": "airpods", "prompt": "airpods case", "name": "AirPods", "icon": "airpods",
     "aliases": ["airpods", "air pods", "earbuds", "earphones", "headphones", "airpods case"]},
]

for _item in CATALOG:
    _item["object_id"] = f"{_item['category'].replace(' ', '_')}_01"

BY_CATEGORY: dict[str, dict] = {c["category"]: c for c in CATALOG}
ALIASES: dict[str, list[str]] = {c["category"]: c["aliases"] for c in CATALOG}
SUPPORTED: list[str] = [c["category"] for c in CATALOG]
