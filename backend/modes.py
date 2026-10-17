"""Monitoring / Scan room (reposition) mode controller.

MONITORING ──start──► REPOSITIONING ──finish──► CALIBRATING ──regions saved──► READY_TO_RESUME
    ▲   (cancel works from any step)                 (waits for a steady view,          │
    └──────────────────────┴──────────────── resume ◄── captures a reference frame) ──┘
"""
from __future__ import annotations

import threading

MONITORING, REPOSITIONING, CALIBRATING, READY_TO_RESUME = (
    "MONITORING", "REPOSITIONING", "CALIBRATING", "READY_TO_RESUME")


class ModeError(Exception):
    pass


class ModeController:
    def __init__(self, memory, steady_frames: int = 5, steady_motion: float = 0.02):
        self.memory = memory
        self.mode = MONITORING
        self.steady_frames = steady_frames
        self.steady_motion = steady_motion
        self._steady = 0
        self.reference_jpeg: bytes | None = None
        self.proposal: list[dict] = []  # areas found by Scan room, for the user to review
        self.reset_tracker = False  # consumed by the vision worker
        self._lock = threading.Lock()

    def status(self) -> dict:
        return {"mode": self.mode, "reference_ready": self.reference_jpeg is not None,
                "proposal": self.proposal,
                "view_id": self.memory.view_id, "paused": self.memory.paused}

    def start(self) -> None:
        with self._lock:
            if self.mode != MONITORING:
                raise ModeError(f"Already {self.mode.lower()}")
            self.memory.pause()  # no location updates, events or snapshots while the camera moves
            self.mode = REPOSITIONING

    def cancel(self) -> bool:
        """Abandon the scan at any step and resume in the same view with the previous areas.

        Returns True if areas were already saved during this scan (the caller restores them)."""
        with self._lock:
            if self.mode == MONITORING:
                raise ModeError("No scan in progress")
            saved = self.mode == READY_TO_RESUME
            self.reference_jpeg, self.proposal, self._steady = None, [], 0
            self.memory.resume(new_view=False)
            self.reset_tracker = True
            self.mode = MONITORING
            return saved

    def finish(self) -> None:
        with self._lock:
            if self.mode != REPOSITIONING:
                raise ModeError("Not repositioning")
            self.reference_jpeg, self.proposal, self._steady = None, [], 0
            self.reset_tracker = True
            self.mode = CALIBRATING

    def on_frame(self, global_motion: float, scan) -> None:
        """Called by the vision worker each frame. Once the view is steady, `scan()` returns
        (reference_jpeg, proposed_areas) from the steady frames."""
        if self.mode != CALIBRATING or self.reference_jpeg is not None:
            return
        self._steady = self._steady + 1 if global_motion < self.steady_motion else 0
        if self._steady >= self.steady_frames:
            self.proposal = []
            jpeg, proposal = scan()
            self.proposal = proposal
            self.reference_jpeg = jpeg

    def regions_saved(self) -> None:
        with self._lock:
            if self.mode == CALIBRATING:
                self.mode = READY_TO_RESUME

    def resume(self) -> None:
        with self._lock:
            if self.mode not in (CALIBRATING, READY_TO_RESUME):
                raise ModeError("Finish repositioning first")
            if self.reference_jpeg is None and self.mode == CALIBRATING:
                raise ModeError("Still waiting for a steady camera view")
            self.memory.resume(new_view=True)
            self.reset_tracker = True
            self.mode = MONITORING
