"""Small box helpers (ported from legacy/lastseen_demo.py)."""
from __future__ import annotations

from lastseen.types import Box


def iou(a, b) -> float:
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0, x2 - x1) * max(0, y2 - y1)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def clamp_box(box, w: int, h: int) -> Box:
    x1, y1, x2, y2 = box
    x1, x2 = max(0, min(w - 1, x1)), max(0, min(w, x2))
    y1, y2 = max(0, min(h - 1, y1)), max(0, min(h, y2))
    return (int(x1), int(y1), int(max(x1 + 2, x2)), int(max(y1 + 2, y2)))
