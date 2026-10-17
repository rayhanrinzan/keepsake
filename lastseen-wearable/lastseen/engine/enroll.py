"""Enrollment: learn what an item looks like from a pick-up / put-down, or from a click.

The session never feeds the ChangeDetector (the vision loop owns that); it only snapshots the
background at start and asks for blobs against that snapshot.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Literal

import cv2

from lastseen.bus import Bus
from lastseen.config import EngineCfg
from lastseen.types import Box
from lastseen.vision.change import ChangeDetector
from lastseen.vision.geometry import clamp_box, iou
from lastseen.vision.identity import Gallery, Identity

logger = logging.getLogger(__name__)

Stage = Literal["waiting_pickup", "waiting_putdown", "settling", "done", "failed"]

MIN_HAND_S = 0.5
HAND_GONE_STEPS = 3
CLICK_BOX = 60
_JITTER = [(0, 0), (1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, -1), (1, -1)]
_JITTER_FRAC = 0.05

MSG_PICKUP = "OK, pick it up and put it down where I can see it."
MSG_PUTDOWN = "Now put it down where I can see it."
MSG_SETTLING = "Hold on, taking a look."
MSG_AMBIGUOUS = "I couldn't tell which thing you put down — try again a bit more in the open"
MSG_TIMEOUT = "I didn't see anything being put down — let's try again."
MSG_ERROR = "Something went wrong saving it — let's try again."
MSG_CANCEL = "Enrollment cancelled."
MSG_LOST = "I lost track of it — try again a bit more in the open"


def _center(b) -> tuple[float, float]:
    return (b[0] + b[2]) / 2, (b[1] + b[3]) / 2


def build_gallery(frame, box: Box, item_id: str, display_name: str, prompt: str | None, ts: float,
                  embedder, identity: Identity, gallery_root, det_boxes,
                  origin: str = "enrolled") -> tuple[Box, Gallery]:
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = box
    for d in det_boxes:
        if iou(d, box) > 0.3:
            x1, y1, x2, y2 = min(x1, d[0]), min(y1, d[1]), max(x2, d[2]), max(y2, d[3])
    box = clamp_box((x1, y1, x2, y2), w, h)
    bw, bh = box[2] - box[0], box[3] - box[1]
    jittered = [clamp_box((box[0] + dx * _JITTER_FRAC * bw, box[1] + dy * _JITTER_FRAC * bh,
                           box[2] + dx * _JITTER_FRAC * bw, box[3] + dy * _JITTER_FRAC * bh), w, h)
                for dx, dy in _JITTER]
    g = Gallery(item_id, Path(gallery_root))
    g.add_pos(embedder.embed(frame, jittered))
    g.neg = identity.build_negatives(frame, box, list(det_boxes))
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
    g.template = gray[box[1]:box[3], box[0]:box[2]].copy()
    g.meta = {"display_name": display_name, "prompt": prompt or display_name,
              "origin": origin, "created_ts": ts}
    g.save()
    return box, g


def enroll_from_click(frame, item_id: str, display_name: str, x: int, y: int, *,
                      change: ChangeDetector, embedder, identity: Identity, gallery_root,
                      prompt: str | None = None, det_boxes=(), ts: float | None = None
                      ) -> tuple[Box, Gallery] | None:
    ts = time.time() if ts is None else ts
    h, w = frame.shape[:2]
    if not (0 <= x < w and 0 <= y < h):
        return None
    box = next((b for b in change.blobs(None, frame) if b[0] <= x < b[2] and b[1] <= y < b[3]), None)
    if box is None:
        half = CLICK_BOX // 2
        box = clamp_box((x - half, y - half, x + half, y + half), w, h)
    return build_gallery(frame, box, item_id, display_name, prompt, ts, embedder, identity,
                         gallery_root, det_boxes)


class EnrollSession:
    def __init__(self, item_id: str, display_name: str, prompt: str | None, change: ChangeDetector,
                 embedder, identity: Identity, gallery_root, bus: Bus, engine_cfg: EngineCfg,
                 timeout_s: float = 20, debug_dir=None):
        self.item_id, self.display_name, self.prompt = item_id, display_name, prompt
        self.debug_dir = debug_dir
        self.change, self.embedder, self.identity = change, embedder, identity
        self.gallery_root, self.bus, self.cfg = gallery_root, bus, engine_cfg
        self.timeout_s = timeout_s
        self.message = ""
        self.stage: Stage = "waiting_pickup"
        self._ref: int | None = change.snapshot()
        self._start_ts: float | None = None
        self._hand_first: float | None = None
        self._hand_last: float | None = None
        self._absent = 0
        self._hand_center: tuple[int, int] | None = None
        self._box: Box | None = None
        self._prev_center: tuple[float, float] | None = None
        self._still = 0
        self._missing = 0
        self._result: tuple[Box, Gallery] | None = None
        self._set(self.stage, MSG_PICKUP)

    def result(self) -> tuple[Box, Gallery] | None:
        return self._result

    def _set(self, stage: Stage, message: str) -> None:
        self.stage, self.message = stage, message
        self.bus.publish("enroll_status", item_id=self.item_id, stage=stage, message=message)
        logger.info("enroll %s: %s", self.item_id, stage)

    def _release(self) -> None:
        if self._ref is not None:
            self.change.drop(self._ref)
            self._ref = None

    def _fail(self, message: str) -> Stage:
        self._release()
        self._set("failed", message)
        return self.stage

    def close(self) -> None:
        """Cancel: release the background ref; fail if not already terminal. Idempotent."""
        self._release()
        if self.stage not in ("done", "failed"):
            self._set("failed", MSG_CANCEL)

    def _hand_seen(self, ts: float, hands: list[Box]) -> None:
        self._absent = 0
        if self._hand_first is None:
            self._hand_first = ts
        self._hand_last = ts
        c = _center(hands[0])
        self._hand_center = (int(c[0]), int(c[1]))

    def _log_ambiguous(self, frame, found: list[Box]) -> None:
        """Diagnostics for a failed put-down search: what changed, where the hand was."""
        try:
            everywhere = self.change.blobs(self._ref, frame)
            logger.warning("enroll %s: %d blob(s) near hand %s (radius %d): %s; %d blob(s) anywhere: %s",
                           self.item_id, len(found), self._hand_center, self.cfg.near_hand_px, found,
                           len(everywhere), everywhere[:8])
            if self.debug_dir is not None:
                img = frame.copy()
                for b in everywhere:
                    cv2.rectangle(img, b[:2], b[2:], (0, 165, 255), 2)
                for b in found:
                    cv2.rectangle(img, b[:2], b[2:], (0, 0, 255), 3)
                if self._hand_center is not None:
                    cv2.circle(img, self._hand_center, self.cfg.near_hand_px, (255, 255, 0), 2)
                Path(self.debug_dir).mkdir(parents=True, exist_ok=True)
                cv2.imwrite(str(Path(self.debug_dir) / f"enroll_debug_{int(time.time())}.jpg"), img)
        except Exception:
            logger.exception("enroll diagnostics failed")

    def step(self, frame, ts: float, hands: list[Box], det_boxes: list[Box]) -> Stage:
        if self.stage in ("done", "failed"):
            return self.stage
        if self._start_ts is None:
            self._start_ts = ts
        if ts - self._start_ts > self.timeout_s:
            return self._fail(MSG_TIMEOUT)

        if self.stage == "waiting_pickup":
            if hands:
                self._hand_seen(ts, hands)
                self._set("waiting_putdown", MSG_PUTDOWN)
        elif self.stage == "waiting_putdown":
            if hands:
                self._hand_seen(ts, hands)
            elif self._hand_first is not None:
                self._absent += 1
                if self._absent < HAND_GONE_STEPS:
                    return self.stage
                if self._hand_last - self._hand_first < MIN_HAND_S:
                    self._hand_first = self._hand_last = None  # a flicker, not a pick-up
                else:
                    found = self.change.blobs(self._ref, frame, near=self._hand_center,
                                              radius=self.cfg.near_hand_px)
                    if len(found) != 1:
                        self._log_ambiguous(frame, found)
                        return self._fail(MSG_AMBIGUOUS)
                    self._box = found[0]
                    self._prev_center = _center(found[0])
                    self._still = self._missing = 0
                    self._set("settling", MSG_SETTLING)
        elif self.stage == "settling":
            if hands:
                self._hand_first = self._hand_last = None
                self._hand_seen(ts, hands)
                self._set("waiting_putdown", MSG_PUTDOWN)
                return self.stage
            c = _center(self._box)
            found = self.change.blobs(self._ref, frame, near=(int(c[0]), int(c[1])),
                                      radius=self.cfg.near_hand_px)
            if not found:
                self._missing += 1
                if self._missing > self.cfg.placed_frames:
                    return self._fail(MSG_LOST)
                return self.stage
            self._missing = 0
            nc = _center(found[0])
            moved = ((nc[0] - self._prev_center[0]) ** 2 + (nc[1] - self._prev_center[1]) ** 2) ** 0.5
            self._still = self._still + 1 if moved < self.cfg.still_px else 0
            self._box, self._prev_center = found[0], nc
            if self._still >= self.cfg.placed_frames:
                try:
                    self._result = build_gallery(frame, self._box, self.item_id, self.display_name,
                                                 self.prompt, ts, self.embedder, self.identity,
                                                 self.gallery_root, det_boxes)
                except Exception:
                    logger.exception("enrollment finalize failed for %s", self.item_id)
                    return self._fail(MSG_ERROR)
                self._release()
                self._set("done", f"Got it. I'll remember your {self.display_name}.")
        return self.stage
