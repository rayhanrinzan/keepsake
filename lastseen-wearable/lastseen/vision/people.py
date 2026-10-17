"""Person tracking (Ultralytics YOLO + ByteTrack) and the "left the camera view" watcher."""
from __future__ import annotations

import logging

import supervision as sv

from lastseen.types import Person

logger = logging.getLogger(__name__)

FORGET_AFTER_S = 10.0


class PeopleTracker:
    def __init__(self, cfg, device: str = "cpu"):
        from ultralytics import YOLO

        self.cfg, self.device = cfg, device
        self.model = YOLO(cfg.model)

    def track(self, frame) -> tuple[list[Person], sv.Detections]:
        res = self.model.track(frame, persist=True, tracker="bytetrack.yaml", classes=[0],
                               device=self.device, verbose=False)[0]
        det = sv.Detections.from_ultralytics(res)
        boxes = res.boxes
        if boxes is None or len(boxes) == 0 or boxes.id is None:
            return [], det
        ids = boxes.id.int().cpu().tolist()
        persons = []
        for tid, xyxy in zip(ids, boxes.xyxy.cpu().tolist()):
            x1, y1, x2, y2 = (int(round(v)) for v in xyxy)
            persons.append(Person(int(tid), (x1, y1, x2, y2), ((x1 + x2) // 2, y2)))
        return persons, det


def safe_track(tracker, frame) -> tuple[list[Person], sv.Detections]:
    """tracker.track(frame), but a failure is logged and yields no people."""
    try:
        return tracker.track(frame)
    except Exception:
        logger.exception("person tracking failed")
        return [], sv.Detections.empty()


class LeaveWatcher:
    """Reports track ids entering the view and leaving it through a frame edge."""

    def __init__(self, frame_wh: tuple[int, int], edge_frac: float = 0.03,
                 leave_after_s: float = 1.0, bus=None):
        self.w, self.h = frame_wh
        self.edge_frac, self.leave_after_s, self.bus = edge_frac, leave_after_s, bus
        self._tracks: dict[int, dict] = {}   # id -> {"box", "seen", "left"}

    def _at_edge(self, b) -> bool:
        f = self.edge_frac
        return b[0] <= f * self.w or b[1] <= f * self.h or b[2] >= (1 - f) * self.w or b[3] >= (1 - f) * self.h

    def _publish(self, event: str, tid: int) -> None:
        if self.bus is not None:
            self.bus.publish("person", event=event, track_id=tid)

    def update(self, persons: list[Person], ts: float) -> tuple[list[int], list[int]]:
        entered, left = [], []
        for p in persons:
            tr = self._tracks.get(p.track_id)
            if tr is None:
                entered.append(p.track_id)
                self._tracks[p.track_id] = {"box": p.box, "seen": ts, "left": False}
                self._publish("entered_view", p.track_id)
            else:
                if tr["left"]:          # came back (same ByteTrack id): a new departure may be reported
                    tr["left"] = False
                    entered.append(p.track_id)
                    self._publish("entered_view", p.track_id)
                tr.update(box=p.box, seen=ts)
        present = {p.track_id for p in persons}
        for tid, tr in list(self._tracks.items()):
            if tid in present:
                continue
            gone = ts - tr["seen"]
            if gone > FORGET_AFTER_S:
                del self._tracks[tid]
            elif gone >= self.leave_after_s and not tr["left"] and self._at_edge(tr["box"]):
                tr["left"] = True
                left.append(tid)
                self._publish("left_view", tid)
        return entered, left
