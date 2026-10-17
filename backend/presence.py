"""Is someone in the room? Debounced person presence from per-frame detections.

A person must be detected for `enter_frames` frames in a row to count as present (so one false
detection never counts), and must then go undetected for `leave_seconds` to count as gone (so a
missed frame or a brief occlusion isn't a departure). Leaving fires the "Are you looking for
something?" prompt in the app.
"""
from __future__ import annotations

import time

PERSON = "person"


class PresenceTracker:
    def __init__(self, enter_frames: int = 3, leave_seconds: float = 2.0, min_conf: float = 0.35):
        self.enter_frames = enter_frames
        self.leave_seconds = leave_seconds
        self.min_conf = min_conf
        self.present = False
        self.left_count = 0  # increments on every departure; the app watches it
        self.left_at: float | None = None  # wall-clock time of the last departure
        self._streak = 0
        self._last_seen = 0.0

    def update(self, observations, now: float | None = None) -> str | None:
        """Advance one frame. Returns "entered", "left" or None."""
        now = time.monotonic() if now is None else now
        seen = any(o.category == PERSON and o.confidence >= self.min_conf for o in observations)
        if seen:
            self._streak += 1
            self._last_seen = now
            if not self.present and self._streak >= self.enter_frames:
                self.present = True
                return "entered"
            return None
        self._streak = 0
        if self.present and now - self._last_seen >= self.leave_seconds:
            self.present = False
            self.left_count += 1
            self.left_at = time.time()
            return "left"
        return None

    def reset(self) -> None:
        """Forget presence without firing (e.g. the camera is being moved)."""
        self.present = False
        self._streak = 0

    def status(self) -> dict:
        return {"person_present": self.present, "person_left_count": self.left_count,
                "person_left_at": self.left_at}
