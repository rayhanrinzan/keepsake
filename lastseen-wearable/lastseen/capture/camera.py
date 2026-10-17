"""Camera thread that keeps only the newest frame (live capture or looping mp4 replay).

Ported from the LatestFrame idea in legacy/lastseen_demo.py: never a lagging queue.
"""
from __future__ import annotations

import logging
import os
import threading
import time

import cv2
import numpy as np

from lastseen.capture.devices import camera_names, find_camera_index

log = logging.getLogger(__name__)

STALE_S = 2.0
OPEN_FAIL_LOG_S = 10.0  # rate limit for "could not open camera" warnings

# macOS AVFoundation can only run its camera-permission request on the main thread; from the
# capture thread it fails the open outright. start() does the first open on the caller's (main)
# thread with the request allowed; reopens from the capture thread skip it.
_SKIP_AUTH = "OPENCV_AVFOUNDATION_SKIP_AUTH"
os.environ.setdefault(_SKIP_AUTH, "1")


def _is_camera_name(src: str) -> bool:
    """A string source is a camera name unless it looks like a file path."""
    return not (os.path.isfile(src) or "/" in src or "\\" in src
                or src.lower().endswith((".mp4", ".mov", ".avi", ".mkv", ".m4v")))


class LatestFrameCamera:
    def __init__(self, source: int | str, width: int, replay: str | None = None):
        self.source = source
        self.width = width
        self.replay = replay
        self._frame: np.ndarray | None = None
        self._ts = 0.0
        self._seq = 0
        self._fps = 0.0
        self._last_mono = 0.0  # monotonic time of last frame
        self._cond = threading.Condition()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="camera", daemon=True)
        self._cap: cv2.VideoCapture | None = None
        self._last_fail_log = 0.0

    # ---- public API ----
    def start(self) -> None:
        if not self.replay:
            self._open_on_caller_thread()
        self._thread.start()

    def _open_on_caller_thread(self) -> None:
        saved = os.environ.pop(_SKIP_AUTH, None)
        try:
            self._open()
        finally:
            if saved is not None:
                os.environ[_SKIP_AUTH] = saved

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=3.0)
        self._release()

    def get_latest(self) -> tuple[np.ndarray | None, float, int]:
        with self._cond:
            if self._frame is None:
                return None, 0.0, 0
            return self._frame, self._ts, self._seq

    @property
    def ok(self) -> bool:
        return self._last_mono > 0 and time.monotonic() - self._last_mono < STALE_S

    @property
    def fps(self) -> float:
        if not self.ok:
            return 0.0
        # decay if frames stopped arriving recently
        gap = time.monotonic() - self._last_mono
        if gap > 0.5 and self._fps > 0:
            return min(self._fps, 1.0 / gap)
        return self._fps

    # ---- internals ----
    def _release(self) -> None:
        cap, self._cap = self._cap, None
        if cap is not None:
            try:
                cap.release()
            except Exception:
                log.exception("capture release failed")

    def _open(self) -> bool:
        self._release()
        try:
            if self.replay:
                cap = cv2.VideoCapture(self.replay)
            else:
                src = self.source
                if isinstance(src, str) and _is_camera_name(src):
                    # A camera name (e.g. "iPhone"): resolve its current index on every open, and
                    # never fall back to a different camera.
                    src = find_camera_index(self.source)
                    if src is None:
                        self._log_open_failure(f"camera {self.source!r} not found (cameras: {camera_names()}); "
                                               "is the iPhone nearby, locked and in landscape?")
                        return False
                cap = cv2.VideoCapture(src)
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            if not cap.isOpened():
                cap.release()
                self._log_open_failure()
                return False
            self._cap = cap
            if self.replay:
                log.info("camera opened: replay %s", self.replay)
            elif src != self.source:
                log.info("camera opened: %r at index %s", self.source, src)
            else:
                log.info("camera opened: index %s", src)
            return True
        except Exception:
            log.exception("camera open failed")
            return False

    def _log_open_failure(self, message: str | None = None) -> None:
        now = time.monotonic()
        if now - self._last_fail_log >= OPEN_FAIL_LOG_S:
            self._last_fail_log = now
            log.warning("%s; retrying", message or (
                f"could not open camera {self.replay or self.source!r} (check lastseen.tools.list_cameras "
                "and camera permission for this terminal)"))

    def _publish(self, frame: np.ndarray) -> None:
        h, w = frame.shape[:2]
        if w != self.width:
            frame = cv2.resize(frame, (self.width, max(1, round(h * self.width / w))),
                               interpolation=cv2.INTER_AREA)
        now = time.monotonic()
        if self._last_mono > 0:
            dt = now - self._last_mono
            if 0 < dt < STALE_S:
                inst = 1.0 / dt
                self._fps = inst if self._fps == 0 else 0.8 * self._fps + 0.2 * inst
            else:
                self._fps = 0.0
        with self._cond:
            self._frame, self._ts, self._seq = frame, time.time(), self._seq + 1
            self._last_mono = now
            self._cond.notify_all()

    def _run(self) -> None:
        last_ok = time.monotonic()
        period = 0.0
        next_t = 0.0
        while not self._stop.is_set():
            try:
                if self._cap is None:
                    if not self._open():
                        self._stop.wait(0.5)
                        continue
                    last_ok = time.monotonic()
                    if self.replay:
                        fps = self._cap.get(cv2.CAP_PROP_FPS)
                        period = 1.0 / fps if fps and fps > 1 else 1.0 / 30
                        next_t = time.monotonic()
                ok, frame = self._cap.read()
                if not ok or frame is None:
                    if self.replay:  # EOF -> loop
                        self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                        ok, frame = self._cap.read()
                    if not ok or frame is None:
                        if time.monotonic() - last_ok > STALE_S:
                            log.warning("no frames for %.0fs, reopening camera", STALE_S)
                            self._release()
                        else:
                            self._stop.wait(0.05)
                        continue
                last_ok = time.monotonic()
                self._publish(frame)
                if self.replay:
                    next_t += period
                    delay = next_t - time.monotonic()
                    if delay > 0:
                        self._stop.wait(delay)
                    else:
                        next_t = time.monotonic()
            except Exception:
                log.exception("camera loop error")
                self._release()
                self._stop.wait(0.5)
