"""TouchWatcher: follows each hand as an episode and reports what it left or took.

A hand episode opens when a hand appears, snapshots the background, and closes after the hand has
been gone HAND_GONE_STEPS ticks. On close: a new region near where the hand let go is "placed";
else a vacated region where the hand first touched is "lifted"; else it was only a brush.
The vision loop owns ChangeDetector.update(); this class only snapshots and asks for blobs.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Literal

import numpy as np

from lastseen.engine.enroll import HAND_GONE_STEPS, MIN_HAND_S, build_gallery
from lastseen.types import Box
from lastseen.vision.change import ChangeDetector
from lastseen.vision.geometry import iou

logger = logging.getLogger(__name__)

MATCH_RADIUS_FACTOR = 1.5


@dataclass
class TouchResult:
    kind: Literal["placed", "lifted"]
    box: Box
    frame: np.ndarray
    ts: float
    last_hand: tuple[int, int]


@dataclass
class _Episode:
    ref: int
    before: np.ndarray
    first_center: tuple[int, int]
    last_center: tuple[int, int]
    first_ts: float
    last_ts: float
    absent: int = 0


def _center(b: Box) -> tuple[int, int]:
    return int((b[0] + b[2]) / 2), int((b[1] + b[3]) / 2)


def _dist(a, b) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


class TouchWatcher:
    def __init__(self, change: ChangeDetector, engine_cfg, max_episodes: int = 2):
        self.change = change
        self.cfg = engine_cfg
        self.max_episodes = max_episodes
        self._episodes: list[_Episode] = []

    def active(self) -> int:
        return len(self._episodes)

    def close_all(self) -> None:
        for ep in self._episodes:
            self.change.drop(ep.ref)
        self._episodes.clear()

    def update(self, frame: np.ndarray, ts: float, hands: list[Box],
               enabled: bool = True) -> list[TouchResult]:
        if not enabled:
            self.close_all()
            return []
        centers = [_center(h) for h in hands]
        limit = MATCH_RADIUS_FACTOR * self.cfg.near_hand_px
        pairs = sorted((_dist(c, ep.last_center), hi, ei)
                       for hi, c in enumerate(centers) for ei, ep in enumerate(self._episodes))
        used_h: set[int] = set()
        used_e: set[int] = set()
        for d, hi, ei in pairs:
            if d > limit or hi in used_h or ei in used_e:
                continue
            used_h.add(hi)
            used_e.add(ei)
            ep = self._episodes[ei]
            ep.last_center, ep.last_ts, ep.absent = centers[hi], ts, 0

        results: list[TouchResult] = []
        keep: list[_Episode] = []
        for ei, ep in enumerate(self._episodes):
            if ei not in used_e:
                ep.absent += 1
                if ep.absent >= HAND_GONE_STEPS:
                    res = self._finish(ep, frame, ts)
                    if res is not None:
                        results.append(res)
                    continue
            keep.append(ep)
        self._episodes = keep

        for hi, c in enumerate(centers):
            if hi in used_h or len(self._episodes) >= self.max_episodes:
                continue
            self._episodes.append(_Episode(ref=self.change.snapshot(), before=frame.copy(),
                                           first_center=c, last_center=c, first_ts=ts, last_ts=ts))
        return results

    def _finish(self, ep: _Episode, frame: np.ndarray, ts: float) -> TouchResult | None:
        try:
            return self._classify(ep, frame, ts)
        except Exception:
            logger.exception("touch episode failed")
            return None
        finally:
            self.change.drop(ep.ref)

    def _classify(self, ep: _Episode, frame: np.ndarray, ts: float) -> TouchResult | None:
        if ep.last_ts - ep.first_ts < MIN_HAND_S:
            return None  # a flicker, not a touch
        r = self.cfg.near_hand_px
        placed = self.change.blobs(ep.ref, frame, near=ep.last_center, radius=r)
        if _dist(ep.first_center, ep.last_center) >= self.cfg.move_px:
            placed = [b for b in placed
                      if _dist(_center(b), ep.last_center) <= _dist(_center(b), ep.first_center)]
        if placed:
            return TouchResult("placed", placed[0], frame, ts, ep.last_center)
        vacated = self.change.blobs(ep.ref, frame, near=ep.first_center, radius=r)
        if vacated:
            return TouchResult("lifted", vacated[0], ep.before, ts, ep.last_center)
        return None


# ---------------------------------------------------------------- vision-loop step (touch-to-track)
TRACKED_IOU = 0.1        # a result overlapping a tracker's bbox / live_box is that tracker's business
DET_IOU = 0.3            # detections this close to the box count as detector support for the classifier
EDGE_FRAC = 0.05         # a lift whose hand was last seen this close to an edge left the view


def _at_edge(pt, wh) -> bool:
    w, h = wh
    return (pt[0] <= EDGE_FRAC * w or pt[0] >= (1 - EDGE_FRAC) * w
            or pt[1] <= EDGE_FRAC * h or pt[1] >= (1 - EDGE_FRAC) * h)


def _in_held_hand(box: Box, trackers, near_px: float) -> bool:
    """A result inside a tracker's live (hand) box, or near a HELD tracker's hand, is that item moving
    in the hand, not a new item: locking it would track one object twice."""
    c = _center(box)
    for t in trackers:
        lb = t.live_box
        if lb is not None and lb[0] <= c[0] <= lb[2] and lb[1] <= c[1] <= lb[3]:
            return True
        if t.state == "HELD":
            anchors = [a for a in [t.hand_anchor(), *t.recent_anchors()] if a is not None]
            if any(_dist(c, a) <= near_px for a in anchors):
                return True
    return False


def handle_touch(loop, frame: np.ndarray, ts: float, hands: list[Box]) -> None:
    """One touch-to-track tick for a VisionLoop: lock at most one untracked configured item."""
    if loop._session is not None:
        loop.touch.update(frame, ts, hands, enabled=False)
        return
    results = loop.touch.update(frame, ts, hands, enabled=True)
    tracked = [b for t in loop.trackers.values() for b in (t.bbox, t.live_box) if b is not None]
    res = next((r for r in results if not any(iou(r.box, b) > TRACKED_IOU for b in tracked)
                and not _in_held_hand(r.box, loop.trackers.values(), loop.cfg.engine.near_hand_px)), None)
    if res is None:
        return
    candidates = list(loop.touch_item_ids)     # all configured items: a tracked one must win honestly
    if not candidates:
        return
    # a "lifted" item is gone from the current frame, so its detections say nothing about it
    dets = loop._dets if res.kind == "placed" else []
    det_ids = [i for i, b, _ in dets if iou(b, res.box) > DET_IOU]
    c = loop.classifier.classify(res.frame, res.box, det_ids, candidates)
    if c.item_id is None:
        logger.info("touch: not locking (%s) %s", c.reason, {k: round(v, 2) for k, v in c.probs.items()})
        return
    if c.item_id in loop.trackers:
        logger.info("touch: already tracked %s", c.item_id)   # its own tracker reacquires it
        return
    it = loop._item(c.item_id)
    name = it.display_name if it is not None else c.item_id
    prompt = it.prompt if it is not None else None
    box, g = build_gallery(res.frame, res.box, c.item_id, name, prompt, ts, loop.embedder, loop.identity,
                           loop.gallery_root, [b for _, b, _ in dets], origin="auto")
    conf = round(c.probs[c.item_id], 2)
    if res.kind == "placed":
        state = "PLACED"
    else:
        state = "CARRIED_OUT" if _at_edge(res.last_hand, (frame.shape[1], frame.shape[0])) else "HELD"
    loop._lock_item(c.item_id, box, g, state=state, confidence=conf, frame=res.frame, anchor=res.last_hand)
    logger.info("touch: locked %s (p=%.2f)", c.item_id, conf)
