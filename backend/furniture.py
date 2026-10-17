"""Scan room: propose room areas from furniture the detector actually sees.

Runs pretrained YOLO on a few steady frames, keeps furniture seen consistently, and merges duplicate
boxes. Pretrained COCO has no "desk", "dresser" or "shelf", so tables become "Table" (rename freely)
and anything else is drawn by hand in the review step.
"""
from __future__ import annotations

# COCO class -> default area name
FURNITURE: dict[str, str] = {
    "bed": "Bed", "couch": "Couch", "chair": "Chair", "dining table": "Table", "bench": "Bench",
    "tv": "TV", "refrigerator": "Fridge", "oven": "Oven", "microwave": "Microwave", "sink": "Sink",
    "toilet": "Toilet",
}


def _iou(a: tuple, b: tuple) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def propose_regions(frames: list[list[tuple[str, float, tuple]]], min_share: float = 0.4,
                    pad: float = 0.02) -> list[dict]:
    """frames: per-frame detections [(coco_class, confidence, (x0,y0,x1,y1) normalized)].

    Returns area dicts {"name", "kind", "camera", "confidence"} for furniture present in at least
    `min_share` of frames, largest first, with numbered names for repeats ("Chair 1", "Chair 2").
    """
    clusters: list[dict] = []  # {"kind", "boxes": [...], "confs": [...], "frames": set}
    for fi, dets in enumerate(frames):
        for kind, conf, box in dets:
            if kind not in FURNITURE:
                continue
            match = max((c for c in clusters if c["kind"] == kind),
                        key=lambda c: _iou(c["mean"], box), default=None)
            if match and _iou(match["mean"], box) > 0.3:
                match["boxes"].append(box)
                match["confs"].append(conf)
                match["frames"].add(fi)
                n = len(match["boxes"])
                match["mean"] = tuple(sum(b[i] for b in match["boxes"]) / n for i in range(4))
            else:
                clusters.append({"kind": kind, "boxes": [box], "confs": [conf], "frames": {fi},
                                 "mean": box})
    need = max(1, round(min_share * len(frames)))
    kept = [c for c in clusters if len(c["frames"]) >= need]
    kept.sort(key=lambda c: (c["mean"][2] - c["mean"][0]) * (c["mean"][3] - c["mean"][1]), reverse=True)

    counts: dict[str, int] = {}
    for c in kept:
        counts[c["kind"]] = counts.get(c["kind"], 0) + 1
    seen: dict[str, int] = {}
    out = []
    for c in kept:
        base = FURNITURE[c["kind"]]
        seen[c["kind"]] = seen.get(c["kind"], 0) + 1
        name = f"{base} {seen[c['kind']]}" if counts[c["kind"]] > 1 else base
        x0, y0, x1, y1 = c["mean"]
        out.append({"name": name, "kind": c["kind"],
                    "camera": [round(max(0.0, x0 - pad), 4), round(max(0.0, y0 - pad), 4),
                               round(min(1.0, x1 + pad), 4), round(min(1.0, y1 + pad), 4)],
                    "confidence": round(sum(c["confs"]) / len(c["confs"]), 2)})
    return out[:16]
