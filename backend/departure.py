"""Possible departures for Departure Alerts (integrations/photon), built on PresenceTracker.

A departure is PresenceTracker's "left": the room went from occupied to empty (someone was seen for
a few frames, then nobody for `leave_seconds`). The Spectrum agent polls these events and decides
whether to send a reminder; nothing here sends messages or touches object memory.

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

log = logging.getLogger("keepsake.departure")


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
        """Turn a new PresenceTracker departure (in the worker status) into an event."""
        left = status.get("person_left_count")
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
            return self._emit("presence", view_id, _iso(status.get("person_left_at")))

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
