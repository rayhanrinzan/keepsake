"""Possible departures for Departure Alerts (integrations/photon).

With many people in view, "the room is empty" never happens, so Departure Alerts follows one person:
the target is the largest person box (usually the closest) seen for a few frames in a row, followed
by ByteTrack id and, when the id changes after an occlusion, by position. A departure is the target
going unseen for `leave_seconds`. Everyone else is ignored while the target is in view.

TargetTracker rides along with PresenceTracker (DeparturePresence, passed to VisionWorker as
`presence`), so it sees the same detections and resets the same way during Scan room, and the
app's own presence prompt is unchanged. The Spectrum agent polls the events and decides whether to
send a reminder; nothing here sends messages or touches object memory.

Departures are dropped while the view can't be trusted (camera shift, dark frames), because then
people "vanish" without leaving. PresenceTracker itself already ignores Scan room.
"""
from __future__ import annotations

import itertools
import logging
import threading
import time
from collections import deque
from datetime import datetime, timezone

from presence import PERSON, PresenceTracker

log = logging.getLogger("keepsake.departure")

Box = tuple[float, float, float, float]


def _area(b: Box) -> float:
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def _iou(a: Box, b: Box) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    return inter / max(1e-9, _area(a) + _area(b) - inter)


def _near(a: Box, b: Box, dist: float) -> bool:
    ax, ay, bx, by = (a[0] + a[2]) / 2, (a[1] + a[3]) / 2, (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
    return abs(ax - bx) <= dist and abs(ay - by) <= dist


class TargetTracker:
    """Follows one person through a crowd; counts that person leaving the view."""

    def __init__(self, acquire_frames: int = 3, leave_seconds: float = 3.0, min_conf: float = 0.35,
                 reacquire_iou: float = 0.3, reacquire_dist: float = 0.12):
        self.acquire_frames = acquire_frames
        self.leave_seconds = leave_seconds
        self.min_conf = min_conf
        self.reacquire_iou = reacquire_iou
        self.reacquire_dist = reacquire_dist
        self.target_id: int | None = None
        self.box: Box | None = None
        self.left_count = 0
        self.left_at: float | None = None
        self.people = 0
        self._last_seen = 0.0
        self._candidate: int | None = None
        self._streak = 0
        self._others: set[int] = set()  # people seen alongside the target: never mistaken for them

    def update(self, observations, now: float | None = None) -> str | None:
        """One frame. Returns "acquired", "left" or None."""
        now = time.monotonic() if now is None else now
        people = {}
        for o in observations:
            if o.category == PERSON and o.confidence >= self.min_conf and o.bbox and o.track_id is not None:
                people[o.track_id] = tuple(o.bbox)
        self.people = len(people)
        if self.target_id is None:
            return self._acquire(people, now)
        if self.target_id in people:
            self.box, self._last_seen = people[self.target_id], now
            self._others = set(people) - {self.target_id}
            return None
        # Target's id is gone: the tracker may have given them a new id after an occlusion.
        for tid, b in people.items():
            if tid not in self._others and (_iou(b, self.box) >= self.reacquire_iou or _near(b, self.box, self.reacquire_dist)):
                self.target_id, self.box, self._last_seen = tid, b, now
                return None
        if now - self._last_seen >= self.leave_seconds:
            self.left_count += 1
            self.left_at = time.time()
            self.reset()
            return "left"
        return None

    def _acquire(self, people: dict, now: float) -> str | None:
        if not people:
            self._candidate, self._streak = None, 0
            return None
        tid = max(people, key=lambda t: _area(people[t]))  # the closest person
        self._streak = self._streak + 1 if tid == self._candidate else 1
        self._candidate = tid
        if self._streak < self.acquire_frames:
            return None
        self.target_id, self.box, self._last_seen = tid, people[tid], now
        self._candidate, self._streak = None, 0
        return "acquired"

    def reset(self) -> None:
        """Forget the target without counting a departure."""
        self.target_id, self.box, self._candidate, self._streak = None, None, None, 0
        self._others = set()

    def status(self) -> dict:
        return {"target_tracking": self.target_id is not None, "target_box":
                [round(v, 3) for v in self.box] if self.box else None,
                "target_left_count": self.left_count, "target_left_at": self.left_at,
                "people_tracked": self.people}


class DeparturePresence(PresenceTracker):
    """PresenceTracker that also feeds a TargetTracker; behaves exactly like the original."""

    def __init__(self, target: TargetTracker | None = None, **kw):
        super().__init__(**kw)
        self.target = target or TargetTracker(min_conf=self.min_conf)

    def update(self, observations, now: float | None = None) -> str | None:
        result = super().update(observations, now)
        try:
            if self.target.update(observations, now) == "left":
                log.info("tracked person left the view")
        except Exception:  # noqa: BLE001 - Departure Alerts must never break tracking
            log.exception("target tracker failed")
        return result

    def reset(self) -> None:
        super().reset()
        self.target.reset()

    def status(self) -> dict:
        return {**super().status(), **self.target.status()}


def hold_reason(modes, memory, status: dict, now: float | None = None) -> str | None:
    """Why departures can't be judged right now (None when the view is trustworthy)."""
    now = time.time() if now is None else now
    if getattr(modes, "mode", "MONITORING") != "MONITORING" or getattr(memory, "paused", False):
        return "camera_repositioning"
    until = getattr(memory, "_suspended_until", None)
    if until is not None and datetime.now(timezone.utc) < until:
        return "camera_shift"
    if now - (status.get("camera_shift_at") or 0) < 10:
        return "camera_shift"
    if status.get("warning") and "black frames" in status["warning"]:
        return "camera_dark"
    if status.get("camera") not in (None, "active"):
        return "camera_unavailable"
    return None


def _iso(ts: float | None) -> str:
    dt = datetime.fromtimestamp(ts, timezone.utc) if ts else datetime.now(timezone.utc)
    return dt.isoformat(timespec="seconds")


class DepartureFeed:
    def __init__(self, maxlen: int = 50):
        self._events: deque[dict] = deque(maxlen=maxlen)
        self._ids = itertools.count(1)
        self._left_seen: int | None = None  # PresenceTracker.left_count already turned into events
        self.suppressed = 0
        self.last_suppressed: str | None = None
        self._lock = threading.Lock()

    def _emit(self, source: str, view_id: str | None, at: str) -> dict:
        ev = {"id": next(self._ids), "type": "possible_departure", "source": source, "at": at,
              "view_id": view_id}
        self._events.append(ev)
        return ev

    def sync(self, status: dict, hold: str | None, view_id: str | None) -> dict | None:
        """Turn a new TargetTracker departure (in the worker status) into an event."""
        left = status.get("target_left_count")
        if left is None:
            return None
        with self._lock:
            if self._left_seen is None or left < self._left_seen:
                self._left_seen = left  # baseline: departures from before we looked don't count
                return None
            if left == self._left_seen:
                return None
            self._left_seen = left
            if hold:
                self.suppressed += 1
                self.last_suppressed = hold
                log.info("person left the view during %s; not a departure", hold)
                return None
            return self._emit("tracked_person", view_id, _iso(status.get("target_left_at")))

    def simulate(self, view_id: str | None = None) -> dict:
        """A developer-triggered departure (Departure Alerts' manual test)."""
        with self._lock:
            return self._emit("manual", view_id, _iso(None))

    def events_after(self, after: int = 0) -> list[dict]:
        with self._lock:
            return [e for e in self._events if e["id"] > after]

    def latest_id(self) -> int:
        with self._lock:
            return self._events[-1]["id"] if self._events else 0

    def status(self) -> dict:
        return {"latest_id": self.latest_id(), "suppressed": self.suppressed,
                "last_suppressed": self.last_suppressed}
