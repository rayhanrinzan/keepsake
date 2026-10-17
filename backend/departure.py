"""Possible-departure detection from the person boxes the vision worker already produces.

Used by Departure Alerts (integrations/photon): the Spectrum agent polls the events and decides
whether to send a reminder. Nothing here sends messages or touches object memory.

A possible departure needs the whole sequence, in one stable view, with one person in frame:

    IDLE ──person seen N frames──► PRESENT ──enters exit zone (after being outside it)──► AT_EXIT
      ▲                              │  ▲                                                  │
      │        gone for absence_s ◄──┘  └──── walks back out of the zone ◄─────────────────┤
      │                                                                     person gone    ▼
      └──── reappears: tracking blip, back to AT_EXIT ◄──────────────────────────────── LEAVING
                                     gone for absence_s ──► emit possible_departure ──► IDLE

Any hold (camera repositioning or scanning, a camera shift, dark frames, a detection error,
a gap in frames, or more than one person) drops back to IDLE without emitting anything.
"""
from __future__ import annotations

import itertools
import json
import threading
import time
from collections import deque
from datetime import datetime, timezone

IDLE, PRESENT, AT_EXIT, LEAVING = "IDLE", "PRESENT", "AT_EXIT", "LEAVING"
SETTING_KEY = "departure_config"

Box = tuple[float, float, float, float]


def overlap(box: Box, zone: Box) -> float:
    """Fraction of `box` that lies inside `zone` (both normalized x0, y0, x1, y1)."""
    ix = max(0.0, min(box[2], zone[2]) - max(box[0], zone[0]))
    iy = max(0.0, min(box[3], zone[3]) - max(box[1], zone[1]))
    area = max(1e-9, (box[2] - box[0]) * (box[3] - box[1]))
    return ix * iy / area


def merge_people(boxes: list[Box], same: float = 0.5) -> list[Box]:
    """Collapse boxes that mostly cover each other into one person.

    Open-vocabulary detectors often put 2-3 overlapping "person" boxes on one person (seen live in
    a dim room); counting those as several people would suppress every departure."""
    kept: list[Box] = []
    for b in sorted(boxes, key=lambda b: (b[2] - b[0]) * (b[3] - b[1]), reverse=True):
        if not any(overlap(b, k) >= same or overlap(k, b) >= same for k in kept):
            kept.append(b)
    return kept


def validate_zone(zone) -> Box | None:
    if zone is None:
        return None
    if len(zone) != 4:
        raise ValueError("exit_zone must be [x0, y0, x1, y1]")
    x0, y0, x1, y1 = (float(v) for v in zone)
    if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
        raise ValueError("exit_zone must be normalized with x0 < x1 and y0 < y1")
    return (x0, y0, x1, y1)


def hold_reason(modes, memory, status: dict, detect_failed: bool = False,
                now: float | None = None) -> str | None:
    """Why departures can't be judged on this frame (None when the view is trustworthy)."""
    now = time.time() if now is None else now
    if getattr(modes, "mode", "MONITORING") != "MONITORING" or getattr(memory, "paused", False):
        return "camera_repositioning"
    until = getattr(memory, "_suspended_until", None)
    if until is not None and datetime.now(timezone.utc) < until:
        return "camera_shift"
    if now - status.get("camera_shift_at", 0) < 10:
        return "camera_shift"
    if detect_failed:
        return "detection_error"
    if status.get("warning") and "black frames" in status["warning"]:
        return "camera_dark"
    return None


class DepartureDetector:
    def __init__(self, db=None, *, present_frames: int = 3, exit_overlap: float = 0.3,
                 outside_overlap: float = 0.1, absence_seconds: float = 2.5,
                 leave_window_seconds: float = 4.0, max_frame_gap: float = 1.5,
                 min_person_conf: float = 0.4, event_gap_seconds: float = 30.0):
        self.db = db
        self.present_frames = present_frames
        self.exit_overlap = exit_overlap
        self.outside_overlap = outside_overlap
        self.absence_seconds = absence_seconds
        self.leave_window_seconds = leave_window_seconds  # exit zone → gone must happen this fast
        self.max_frame_gap = max_frame_gap  # longer gaps (camera dropped) restart the sequence
        self.min_person_conf = min_person_conf
        self.event_gap_seconds = event_gap_seconds
        self.enabled = False
        self.exit_zone: Box | None = None
        self.state = IDLE
        self.hold: str | None = None
        self.person_count = 0
        self.people: list[list[float]] = []  # merged person boxes on the latest frame (for tuning)
        self._seen = 0
        self._was_outside = False
        self._last_at_exit = 0.0
        self._gone_since = 0.0
        self._last_frame: float | None = None
        self._last_event_at = float("-inf")
        self._events: deque[dict] = deque(maxlen=50)
        self._ids = itertools.count(1)
        self._lock = threading.Lock()
        self._load()

    # ---- config ----
    def _load(self) -> None:
        raw = self.db.get_setting(SETTING_KEY) if self.db else None
        if raw:
            cfg = json.loads(raw)
            self.enabled = bool(cfg.get("enabled", False))
            self.exit_zone = validate_zone(cfg.get("exit_zone"))

    def configure(self, enabled: bool, exit_zone) -> dict:
        zone = validate_zone(exit_zone)
        with self._lock:
            self.enabled, self.exit_zone = enabled, zone
            self._reset()
            if self.db:
                self.db.set_setting(SETTING_KEY, json.dumps(
                    {"enabled": enabled, "exit_zone": list(zone) if zone else None}))
        return self.status()

    def status(self) -> dict:
        return {"enabled": self.enabled, "exit_zone": list(self.exit_zone) if self.exit_zone else None,
                "state": self.state, "hold": self.hold, "person_count": self.person_count,
                "people": self.people,
                "latest_id": self._events[-1]["id"] if self._events else 0}

    # ---- events ----
    def events_after(self, after: int = 0) -> list[dict]:
        with self._lock:
            return [e for e in self._events if e["id"] > after]

    def _emit(self, source: str, view_id: str | None) -> dict:
        ev = {"id": next(self._ids), "type": "possible_departure", "source": source,
              "at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "view_id": view_id}
        self._events.append(ev)
        return ev

    def simulate(self, view_id: str | None = None) -> dict:
        """A developer-triggered departure (Departure Alerts' manual test)."""
        with self._lock:
            return self._emit("manual", view_id)

    # ---- per frame ----
    def _reset(self) -> None:
        self.state, self._seen, self._was_outside = IDLE, 0, False

    def feed(self, people: list[tuple[Box, float]], hold: str | None = None,
             now: float | None = None, view_id: str | None = None) -> dict | None:
        """One processed frame: person (bbox, confidence) pairs. Returns an event when emitted."""
        now = time.monotonic() if now is None else now
        with self._lock:
            gap = self._last_frame is not None and now - self._last_frame > self.max_frame_gap
            self._last_frame = now
            boxes = merge_people([b for b, c in people if c >= self.min_person_conf])
            self.person_count = len(boxes)
            self.people = [[round(v, 3) for v in b] for b in boxes]
            if gap:
                hold = hold or "frame_gap"
            if not hold and len(boxes) > 1:
                hold = "multiple_people"  # can't tell who left; never guess
            self.hold = hold
            if not self.enabled or self.exit_zone is None or hold:
                self._reset()
                return None
            return self._step(boxes[0] if boxes else None, now, view_id)

    def _step(self, box: Box | None, now: float, view_id: str | None) -> dict | None:
        zone = self.exit_zone
        if self.state == IDLE:
            self._seen = self._seen + 1 if box else 0
            if self._seen >= self.present_frames:
                self.state = PRESENT
                self._was_outside = overlap(box, zone) < self.outside_overlap
                self._gone_since = 0.0
            return None
        if self.state == PRESENT:
            if box is None:
                self._gone_since = self._gone_since or now
                if now - self._gone_since >= self.absence_seconds:
                    self._reset()  # left view somewhere other than the exit: no departure
                return None
            self._gone_since = 0.0
            ov = overlap(box, zone)
            if ov < self.outside_overlap:
                self._was_outside = True
            elif ov >= self.exit_overlap and self._was_outside:
                self.state, self._last_at_exit = AT_EXIT, now
            return None
        if self.state == AT_EXIT:
            if box is None:
                if now - self._last_at_exit <= self.leave_window_seconds:
                    self.state, self._gone_since = LEAVING, now
                else:
                    self._reset()
                return None
            if overlap(box, zone) >= self.exit_overlap:
                self._last_at_exit = now
            elif overlap(box, zone) < self.outside_overlap:
                self.state = PRESENT  # walked back into the room
            return None
        # LEAVING
        if box is not None:
            self.state = AT_EXIT if overlap(box, zone) >= self.outside_overlap else PRESENT
            self._last_at_exit = now
            return None  # brief tracking loss, not a departure
        if now - self._gone_since < self.absence_seconds:
            return None
        self._reset()
        if now - self._last_event_at < self.event_gap_seconds:
            return None
        self._last_event_at = now
        return self._emit("detector", view_id)
