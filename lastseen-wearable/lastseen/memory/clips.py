"""Event snapshots and short clips (the only frames ever written to disk)."""
from __future__ import annotations

import datetime as _dt
import logging
import time
from pathlib import Path

import cv2
import numpy as np

from lastseen.types import Box

log = logging.getLogger("lastseen.clips")


def _stamp() -> str:
    return _dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")


def write_snapshot(frame: np.ndarray, bbox: Box, label: str, out_dir: Path) -> Path:
    """Spotlight + circle bbox on a copy of frame, with the zone label. Never mutates frame."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    img = frame.copy()
    h, w = img.shape[:2]
    x1, y1, x2, y2 = (int(v) for v in bbox)
    x1, x2 = max(0, min(x1, w - 1)), max(0, min(x2, w - 1))
    y1, y2 = max(0, min(y1, h - 1)), max(0, min(y2, h - 1))
    cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
    r = int(max(x2 - x1, y2 - y1) * 0.9) + 20
    dim = (img * 0.45).astype(np.uint8)
    mask = np.zeros((h, w), np.uint8)
    cv2.circle(mask, (cx, cy), r, 255, -1)
    img = np.where(mask[..., None] > 0, img, dim)
    cv2.circle(img, (cx, cy), r, (0, 220, 255), 4, cv2.LINE_AA)
    cv2.circle(img, (cx, cy), r + 10, (0, 220, 255), 1, cv2.LINE_AA)
    cv2.rectangle(img, (x1, y1), (x2, y2), (0, 255, 120), 2, cv2.LINE_AA)
    if label:
        font, scale, thick = cv2.FONT_HERSHEY_DUPLEX, 1.0, 2
        (tw, th), _ = cv2.getTextSize(label, font, scale, thick)
        tx = min(max(8, cx - tw // 2), max(8, w - tw - 8))
        ty = cy - r - 18
        if ty - th < 4:
            ty = min(h - 8, cy + r + 18 + th)
        cv2.putText(img, label, (tx, ty), font, scale, (0, 0, 0), thick + 3, cv2.LINE_AA)
        cv2.putText(img, label, (tx, ty), font, scale, (255, 255, 255), thick, cv2.LINE_AA)
    path = out_dir / f"snap_{_stamp()}.jpg"
    if not cv2.imwrite(str(path), img):
        raise OSError(f"could not write snapshot {path}")
    return path


def write_clip(frames: list[tuple[float, np.ndarray]], out_dir: Path, fps: int = 8) -> Path | None:
    """Write (ts, frame) pairs as an mp4. Returns None when empty or no codec works."""
    if not frames:
        return None
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    h, w = frames[0][1].shape[:2]
    path = out_dir / f"clip_{_stamp()}.mp4"
    writer = None
    for fourcc in ("avc1", "mp4v"):
        wr = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*fourcc), fps, (w, h))
        if wr.isOpened():
            writer = wr
            break
        wr.release()
    if writer is None:
        log.warning("could not open a video writer for %s", path)
        path.unlink(missing_ok=True)
        return None
    try:
        for _, f in frames:
            if f.shape[:2] != (h, w):
                f = cv2.resize(f, (w, h))
            writer.write(f)
    finally:
        writer.release()
    return path


def cleanup_old(out_dir: Path, max_age_s: float = 86400) -> int:
    out_dir = Path(out_dir)
    if not out_dir.is_dir():
        return 0
    cutoff = time.time() - max_age_s
    n = 0
    for p in out_dir.iterdir():
        try:
            if p.is_file() and p.stat().st_mtime < cutoff:
                p.unlink()
                n += 1
        except OSError:
            log.warning("cleanup failed for %s", p, exc_info=True)
    return n
