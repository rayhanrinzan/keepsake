"""Object-memory photographs: saved locally when a placement is confirmed, never uploaded.

Encoding and disk writes happen on a background thread so inference never waits on I/O.
Images are full camera frames (for context); the object's bounding box is stored as metadata.
"""
from __future__ import annotations

import logging
import math
import queue
import re
import threading
import time
import uuid
from pathlib import Path

import cv2
import numpy as np

from database import Database

log = logging.getLogger("keepsake.snapshots")
FILENAME_RE = re.compile(r"^[a-z0-9_]+-[0-9a-f]{32}\.jpg$")


class SnapshotStore:
    def __init__(self, db: Database, directory: str | Path, retention: int = 20,
                 cooldown_seconds: float = 3.0, dedupe_distance: float = 0.04,
                 max_width: int = 1280):
        self.db = db
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.retention = retention
        self.cooldown = cooldown_seconds
        self.dedupe = dedupe_distance
        self.max_width = max_width
        self._recent: dict[str, tuple[float, float, float]] = {}  # object_id -> (time, cx, cy)
        self._q: queue.Queue = queue.Queue(maxsize=16)
        threading.Thread(target=self._writer, daemon=True, name="snapshot-writer").start()

    @property
    def enabled(self) -> bool:
        return self.db.get_setting("capture_enabled", "1") == "1"

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self.db.set_setting("capture_enabled", "1" if value else "0")

    def submit(self, event: dict, frame: np.ndarray | None, on_saved=None) -> bool:
        """Queue a snapshot for a confirmed event. Returns False if skipped.

        `on_saved(snapshot_id)` runs on the writer thread once the photo is stored."""
        if frame is None or not self.enabled or not event.get("bbox"):
            return False
        x0, y0, x1, y1 = event["bbox"]
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        prev = self._recent.get(event["object_id"])
        now = time.monotonic()
        if prev and now - prev[0] < self.cooldown and math.hypot(cx - prev[1], cy - prev[2]) < self.dedupe:
            return False  # duplicate of a photo we just took
        self._recent[event["object_id"]] = (now, cx, cy)
        try:
            self._q.put_nowait((event, frame, on_saved))
        except queue.Full:
            log.warning("snapshot queue full; dropping %s", event["object_id"])
            return False
        return True

    def flush(self, timeout: float = 5.0) -> None:
        deadline = time.monotonic() + timeout
        while self._q.unfinished_tasks and time.monotonic() < deadline:
            time.sleep(0.01)

    def _writer(self) -> None:
        while True:
            event, frame, on_saved = self._q.get()
            try:
                snap_id = self._write(event, frame)
                if snap_id is not None and on_saved:
                    on_saved(snap_id)
            except Exception:  # noqa: BLE001
                log.exception("snapshot write failed")
            finally:
                self._q.task_done()

    def _write(self, event: dict, frame: np.ndarray) -> int | None:
        h, w = frame.shape[:2]
        if w > self.max_width:
            frame = cv2.resize(frame, (self.max_width, int(h * self.max_width / w)))
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if not ok:
            return None
        name = f"{event['object_id']}-{uuid.uuid4().hex}.jpg"
        (self.dir / name).write_bytes(buf.tobytes())
        x0, y0, x1, y1 = event["bbox"]
        snap_id = self.db.add_snapshot({
            "object_id": event["object_id"], "event_type": event["event_type"],
            "timestamp": event.get("frame_time") or event["timestamp"], "region": event.get("region"),
            "x0": round(x0, 4), "y0": round(y0, 4), "x1": round(x1, 4), "y1": round(y1, 4),
            "confidence": event["confidence"], "filename": name, "view_id": event.get("view_id")})
        for old in self.db.prune_snapshots(event["object_id"], self.retention):
            self._unlink(old)
        return snap_id

    def highlighted(self, snap: dict) -> bytes | None:
        """The stored photo as JPEG bytes with a circle drawn around the item's bounding box.

        Rendered on request so the stored photo stays clean for the app's own overlay."""
        path = self.path_for(snap["filename"])
        image = cv2.imread(str(path)) if path else None
        if image is None:
            return None
        h, w = image.shape[:2]
        x0, y0, x1, y1 = snap["x0"] * w, snap["y0"] * h, snap["x1"] * w, snap["y1"] * h
        center = (int((x0 + x1) / 2), int((y0 + y1) / 2))
        # Pad the box so the circle surrounds the item instead of cutting through it.
        axes = (max(int((x1 - x0) * 0.75), 24), max(int((y1 - y0) * 0.75), 24))
        thickness = max(4, w // 160)
        # White, like the app's photo box, on a thin dark edge so it still shows on light surfaces.
        cv2.ellipse(image, center, axes, 0, 0, 360, (0, 0, 0), thickness + 3, cv2.LINE_AA)
        cv2.ellipse(image, center, axes, 0, 0, 360, (255, 255, 255), thickness, cv2.LINE_AA)
        ok, buf = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 85])
        return buf.tobytes() if ok else None

    def path_for(self, filename: str) -> Path | None:
        if not FILENAME_RE.match(filename):
            return None
        p = (self.dir / filename).resolve()
        return p if p.parent == self.dir.resolve() and p.is_file() else None

    def _unlink(self, filename: str) -> None:
        p = self.path_for(filename)
        if p:
            p.unlink(missing_ok=True)

    def clear(self) -> None:
        """Delete every stored photo (call alongside clearing the database)."""
        self.flush()
        self._recent.clear()
        for p in self.dir.glob("*.jpg"):
            if FILENAME_RE.match(p.name):
                p.unlink(missing_ok=True)
