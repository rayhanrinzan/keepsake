"""Ring buffer of the last few seconds of downscaled frames, for event clips."""
from __future__ import annotations

import threading
from collections import deque

import cv2
import numpy as np


class RingBuffer:
    def __init__(self, seconds: float = 6.0, width: int = 640):
        self.seconds = seconds
        self.width = width
        self._items: deque[tuple[float, np.ndarray]] = deque()
        self._lock = threading.Lock()

    def push(self, frame: np.ndarray, ts: float) -> None:
        h, w = frame.shape[:2]
        if w != self.width:
            frame = cv2.resize(frame, (self.width, max(1, round(h * self.width / w))),
                               interpolation=cv2.INTER_AREA)
        with self._lock:
            self._items.append((ts, frame))
            cutoff = ts - self.seconds
            while self._items and self._items[0][0] < cutoff:
                self._items.popleft()

    def window(self, t0: float, t1: float) -> list[tuple[float, np.ndarray]]:
        with self._lock:
            return [(t, f) for t, f in self._items if t0 <= t <= t1]
