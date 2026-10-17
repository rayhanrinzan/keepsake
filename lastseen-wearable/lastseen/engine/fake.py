"""Scripted tracker: publishes pick/place events so downstream code can be built without vision."""
from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

import numpy as np

from lastseen.memory.clips import write_clip, write_snapshot
from lastseen.types import Box, TrackerEvent

log = logging.getLogger("lastseen.fake")

TRAY: Box = (300, 420, 370, 470)
DESK: Box = (820, 360, 890, 410)
_BOXES = {"tray": TRAY, "desk": DESK}


class FakeTracker:
    def __init__(self, store, bus, camera, clips_dir, item_id="airpods", display_name="AirPods"):
        self.store, self.bus, self.camera = store, bus, camera
        self.clips_dir = Path(clips_dir)
        self.item_id, self.display_name = item_id, display_name
        self._src, self._dst = "tray", "desk"
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _frame(self) -> np.ndarray:
        frame, _, _ = self.camera.get_latest()
        if frame is None:
            return np.full((720, 1280, 3), 25, np.uint8)
        return frame.copy()

    def _upsert(self, state, zone, bbox, ts, event_id=None):
        self.store.upsert_item(self.item_id, self.display_name, False, state, zone, bbox,
                               0.9, ts, event_id)

    def _pick(self) -> None:
        ts = time.time()
        self.store.add_event(TrackerEvent("PICKED_UP", self.item_id, ts, self._src, None,
                                          _BOXES[self._src], 0.9))
        self._upsert("HELD", None, _BOXES[self._src], ts)

    def _place(self) -> None:
        ts = time.time()
        box, zone = _BOXES[self._dst], self._dst
        frame = self._frame()
        snap = write_snapshot(frame, box, zone, self.clips_dir)
        clip = write_clip([(ts, frame)] * 24, self.clips_dir, fps=8)
        eid = self.store.add_event(
            TrackerEvent("PLACED", self.item_id, ts, None, zone, box, 0.9),
            snapshot_path=str(snap), clip_path=str(clip) if clip else None)
        self._upsert("PLACED", zone, box, ts, eid)
        self._src, self._dst = self._dst, self._src

    def step_once(self) -> None:
        self._pick()
        self._place()

    def _run(self) -> None:
        while not self._stop.wait(20):
            try:
                self._pick()
            except Exception:
                log.exception("fake tracker pick failed")
                continue
            if self._stop.wait(3):
                break
            try:
                self._place()
            except Exception:
                log.exception("fake tracker place failed")

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="fake-tracker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
