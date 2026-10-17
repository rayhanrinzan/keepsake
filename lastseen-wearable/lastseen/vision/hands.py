"""MediaPipe Tasks HandLandmarker wrapper -> padded hand boxes."""
from __future__ import annotations

import os

import cv2
import mediapipe as mp
from mediapipe.tasks.python import BaseOptions, vision

from lastseen.types import Box

MODEL_URL = ("https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
             "hand_landmarker/float16/latest/hand_landmarker.task")
PAD = 0.2


class HandDetector:
    def __init__(self, model_path: str = "models/hand_landmarker.task"):
        if not os.path.exists(model_path):
            raise FileNotFoundError(f"Hand landmarker model not found at {model_path}. Download it from {MODEL_URL}")
        opts = vision.HandLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=model_path),
            running_mode=vision.RunningMode.VIDEO,
            num_hands=2,
        )
        self._lm = vision.HandLandmarker.create_from_options(opts)
        self._last_ts = -1

    def detect(self, frame, ts_ms: int) -> list[Box]:
        ts_ms = int(ts_ms)
        if ts_ms <= self._last_ts:
            ts_ms = self._last_ts + 1
        self._last_ts = ts_ms
        h, w = frame.shape[:2]
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        res = self._lm.detect_for_video(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb), ts_ms)
        boxes: list[Box] = []
        for hand in res.hand_landmarks:
            xs = [p.x * w for p in hand]
            ys = [p.y * h for p in hand]
            x1, x2, y1, y2 = min(xs), max(xs), min(ys), max(ys)
            px, py = (x2 - x1) * PAD, (y2 - y1) * PAD
            boxes.append((max(0, int(x1 - px)), max(0, int(y1 - py)),
                          min(w, int(round(x2 + px))), min(h, int(round(y2 + py)))))
        return boxes

    def close(self) -> None:
        self._lm.close()
