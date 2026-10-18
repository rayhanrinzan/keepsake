"""Background model + change blobs: finds "something new appeared here" regions."""
from __future__ import annotations

import time

import cv2
import numpy as np

from lastseen.types import Box

MIN_AREA_FRAC = 0.0002   # 0.02% of the frame
MAX_AREA_FRAC = 0.05     # 5% of the frame
DIFF_THRESHOLD = 25
LEARN_ALPHA = 0.1
HAND_QUIET_S = 1.0       # learn only after this long with no hands
HAND_PAD = 0.2


class ChangeDetector:
    def __init__(self, work_width: int = 640):
        self.work_width = work_width
        self._bg: np.ndarray | None = None   # float32 grayscale at work resolution
        self._refs: dict[int, np.ndarray] = {}
        self._next_ref = 1
        self._last_hand_ts = float("-inf")
        self._scale = 1.0                    # work px per full-frame px

    def _prep(self, frame: np.ndarray) -> np.ndarray:
        h, w = frame.shape[:2]
        self._scale = min(1.0, self.work_width / w)
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
        if self._scale < 1.0:
            gray = cv2.resize(gray, (max(1, round(w * self._scale)), max(1, round(h * self._scale))),
                              interpolation=cv2.INTER_AREA)
        return cv2.GaussianBlur(gray, (5, 5), 0).astype(np.float32)

    def update(self, frame: np.ndarray, hands: list[Box], ts: float | None = None) -> None:
        ts = time.time() if ts is None else ts
        gray = self._prep(frame)
        if self._bg is None or self._bg.shape != gray.shape:
            self._bg = gray.copy()
            if hands:
                self._last_hand_ts = ts
            return
        if hands:
            self._last_hand_ts = ts
            return
        if ts - self._last_hand_ts < HAND_QUIET_S:
            return
        cv2.accumulateWeighted(gray, self._bg, LEARN_ALPHA)

    def snapshot(self) -> int:
        if self._bg is None:
            raise RuntimeError("snapshot() before any update()")
        ref_id = self._next_ref
        self._next_ref += 1
        self._refs[ref_id] = self._bg.copy()
        return ref_id

    def drop(self, ref_id: int) -> None:
        """Delete a reference. Unknown ids are ignored; using a dropped id in blobs() raises KeyError."""
        self._refs.pop(ref_id, None)

    def blobs(self, ref_id: int | None, frame: np.ndarray, near: tuple[int, int] | None = None,
              radius: int | None = None) -> list[Box]:
        ref = self._bg if ref_id is None else self._refs[ref_id]
        if ref is None:
            return []
        h, w = frame.shape[:2]
        gray = self._prep(frame)
        if gray.shape != ref.shape:
            return []
        diff = np.abs(gray - ref)
        mask = (diff > DIFF_THRESHOLD).astype(np.uint8) * 255
        k = np.ones((3, 3), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, k)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        work_area = mask.shape[0] * mask.shape[1]
        s = self._scale
        out: list[tuple[Box, float, float]] = []
        for c in contours:
            x, y, bw, bh = cv2.boundingRect(c)
            area = cv2.contourArea(c)
            if not (MIN_AREA_FRAC * work_area <= area <= MAX_AREA_FRAC * work_area):
                continue
            box = (int(x / s), int(y / s), min(w, int(np.ceil((x + bw) / s))), min(h, int(np.ceil((y + bh) / s))))
            cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
            dist = float(np.hypot(cx - near[0], cy - near[1])) if near is not None else 0.0
            if near is not None and radius is not None and dist > radius:
                continue
            out.append((box, dist, area))
        if near is not None:
            out.sort(key=lambda t: t[1])
        else:
            out.sort(key=lambda t: -t[2])
        return [b for b, _, _ in out]
