"""Optional hand detection with MediaPipe (issue #5). Keepsake runs fine without it.

Install:  .venv/bin/pip install mediapipe
Model (newer MediaPipe releases only ship the Tasks API, which needs this file):
  curl -L -o backend/models/hand_landmarker.task \
    https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task

Hands come back as normalized boxes around the 21 landmarks (padded a little), which is all the
interaction logic in wearable.py uses. Frames are processed in memory only.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

import cv2
import numpy as np

from wearable import Hand

log = logging.getLogger("keepsake.hands")
DEFAULT_MODEL = Path(__file__).parent / "models" / "hand_landmarker.task"


def _box(points, pad: float = 0.02) -> tuple[float, float, float, float]:
    xs = [p.x for p in points]
    ys = [p.y for p in points]
    return (max(0.0, min(xs) - pad), max(0.0, min(ys) - pad),
            min(1.0, max(xs) + pad), min(1.0, max(ys) + pad))


class HandDetector:
    def __init__(self, model_path: str | Path | None = None, max_hands: int = 2,
                 min_confidence: float = 0.5, width: int = 640):
        self.available = False
        self.reason = ""
        self.width = width
        self._detect = None
        try:
            import mediapipe as mp
        except ImportError:
            self.reason = "mediapipe not installed (pip install mediapipe)"
            log.info("hand detection off: %s", self.reason)
            return
        model_path = Path(model_path or os.getenv("CTRLF_HAND_MODEL", str(DEFAULT_MODEL)))
        try:
            if model_path.exists():  # Tasks API (current MediaPipe)
                from mediapipe.tasks.python import BaseOptions
                from mediapipe.tasks.python.vision import HandLandmarker, HandLandmarkerOptions
                lm = HandLandmarker.create_from_options(HandLandmarkerOptions(
                    base_options=BaseOptions(model_asset_path=str(model_path)), num_hands=max_hands,
                    min_hand_detection_confidence=min_confidence))

                def detect(rgb):
                    res = lm.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb))
                    return [Hand(_box(h), float(c[0].score))
                            for h, c in zip(res.hand_landmarks, res.handedness)]
            elif hasattr(mp, "solutions"):  # legacy API (older MediaPipe)
                legacy = mp.solutions.hands.Hands(static_image_mode=False, max_num_hands=max_hands,
                                                  min_detection_confidence=min_confidence)

                def detect(rgb):
                    res = legacy.process(rgb)
                    marks = res.multi_hand_landmarks or []
                    hand = res.multi_handedness or []
                    return [Hand(_box(m.landmark), float(h.classification[0].score))
                            for m, h in zip(marks, hand)]
            else:
                self.reason = f"hand model missing: download it to {model_path} (see hands.py)"
                log.warning("hand detection off: %s", self.reason)
                return
        except Exception as e:  # noqa: BLE001
            self.reason = f"MediaPipe failed to start: {e}"
            log.exception("hand detection off")
            return
        self._detect = detect
        self.available = True
        log.info("hand detection on (MediaPipe)")

    def detect(self, frame_bgr: np.ndarray) -> list[Hand]:
        if not self.available:
            return []
        h, w = frame_bgr.shape[:2]
        if w > self.width:
            frame_bgr = cv2.resize(frame_bgr, (self.width, int(h * self.width / w)))
        rgb = np.ascontiguousarray(cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB))
        try:
            return self._detect(rgb)
        except Exception:  # noqa: BLE001
            log.exception("hand detection failed; turning it off")
            self.available, self.reason = False, "hand detection crashed (see log)"
            return []
