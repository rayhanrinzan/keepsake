"""Room areas: named rectangles in camera space, found by Scan room (furniture detection) or drawn by hand.

Items are located by the most specific area containing them. Items outside every area are described
relative to the nearest area ("Near Couch") or, failing that, by which part of the view they're in.
"""
from __future__ import annotations

import json
import math
import os
from dataclasses import asdict, dataclass
from pathlib import Path

DEFAULT_REGIONS_PATH = Path(__file__).with_name("regions.json")
NEAR_DISTANCE = 0.08  # normalized distance from an area's edge that still counts as "near" it
SIDES = ("Left side", "Middle", "Right side")

# Preposition used when speaking about an item in an area of this kind.
PREPOSITION = {"tv": "by", "refrigerator": "by", "oven": "by", "microwave": "by", "toilet": "by",
               "sink": "by"}


@dataclass(frozen=True)
class Region:
    name: str
    # Camera-space rectangle, normalized 0..1 (x0,y0 top-left; x1,y1 bottom-right).
    x0: float
    y0: float
    x1: float
    y1: float
    kind: str = "custom"  # COCO furniture class it was detected as, or "custom" if drawn by hand

    def contains(self, x: float, y: float) -> bool:
        return self.x0 <= x <= self.x1 and self.y0 <= y <= self.y1

    def distance(self, x: float, y: float) -> float:
        dx = max(self.x0 - x, 0.0, x - self.x1)
        dy = max(self.y0 - y, 0.0, y - self.y1)
        return math.hypot(dx, dy)

    @property
    def area(self) -> float:
        return (self.x1 - self.x0) * (self.y1 - self.y0)

    def to_dict(self) -> dict:
        return asdict(self)


def load_regions(path: str | os.PathLike | None = None) -> list[Region]:
    path = Path(path or os.getenv("CTRLF_REGIONS", DEFAULT_REGIONS_PATH))
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    return [Region(r["name"], *r["camera"], kind=r.get("kind", "custom")) for r in data["regions"]]


def region_for_point(x: float, y: float, regions: list[Region]) -> str | None:
    """Name of the most specific (smallest) area containing the point, or None."""
    inside = [r for r in regions if r.contains(x, y)]
    return min(inside, key=lambda r: r.area).name if inside else None


def locate(x: float, y: float, regions: list[Region]) -> str:
    """Human location label for a normalized point: an area, 'Near <area>', or a side of the view."""
    name = region_for_point(x, y, regions)
    if name:
        return name
    if regions:
        nearest = min(regions, key=lambda r: r.distance(x, y))
        if nearest.distance(x, y) <= NEAR_DISTANCE:
            return f"Near {nearest.name}"
    return SIDES[min(2, int(x * 3))]


def place_phrase(label: str, regions: list[Region] | None = None) -> str:
    """'on the bed', 'near the couch', 'on the left side of the room'…"""
    if label in ("Left side", "Right side"):
        return f"on the {label.lower()} of the room"
    if label == "Middle":
        return "in the middle of the room"
    if label.startswith("Near "):
        return f"near the {label[5:].lower()}"
    kind = next((r.kind for r in regions or [] if r.name == label), "custom")
    return f"{PREPOSITION.get(kind, 'on')} the {label.lower()}"


def validate_regions(items: list[dict]) -> list[Region]:
    """Build regions from API/JSON dicts, rejecting malformed rectangles."""
    if len(items) > 16:
        raise ValueError("Use at most 16 areas")
    out, names = [], set()
    for it in items:
        name = " ".join(str(it.get("name", "")).split())
        if not name or len(name) > 32 or name.lower() in names:
            raise ValueError(f"Each area needs a unique name (problem: {name!r})")
        if name.lower().startswith("near ") or name in SIDES:
            raise ValueError(f"{name!r} is reserved; pick another name")
        names.add(name.lower())
        x0, y0, x1, y1 = (float(v) for v in it["camera"])
        if not all(0.0 <= v <= 1.0 for v in (x0, y0, x1, y1)):
            raise ValueError("Coordinates must be between 0 and 1")
        if x1 - x0 < 0.02 or y1 - y0 < 0.02:
            raise ValueError(f"Area {name} is too small")
        out.append(Region(name, x0, y0, x1, y1, kind=str(it.get("kind", "custom"))[:32]))
    return out


def save_regions(regions: list[Region], path: str | os.PathLike | None = None) -> None:
    path = Path(path or os.getenv("CTRLF_REGIONS", DEFAULT_REGIONS_PATH))
    rows = [json.dumps({"name": r.name, "kind": r.kind,
                        "camera": [round(v, 4) for v in (r.x0, r.y0, r.x1, r.y1)]}) for r in regions]
    text = ('{\n  "_comment": "Room areas in camera space: [x0, y0, x1, y1] normalized to the frame. '
            'Written by Scan room.",\n  "regions": [' + ("\n    " + ",\n    ".join(rows) + "\n  " if rows else "")
            + "]\n}\n")
    tmp = path.with_suffix(".tmp")
    tmp.write_text(text)
    tmp.replace(path)
