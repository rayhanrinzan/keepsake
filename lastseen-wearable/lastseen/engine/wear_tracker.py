"""Wearable counterpart of `ItemTracker`: a per-item state machine for a camera worn on the chest.

The camera moves, so a position means nothing. We only track what the wearer touches (hand on item
for `touch_s`), then follow it through put-down, going out of view, and being seen again. No zones.
Pure: no models, no I/O. Phases: UNTRACKED, HELD, PLACED_VISIBLE, PLACED_GONE, WITH_YOU.
"""
from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass
from typing import Literal

import numpy as np

from lastseen.config import EngineCfg, WearableCfg
from lastseen.types import Box, Candidate, TrackerEvent
from lastseen.vision.geometry import iou

logger = logging.getLogger(__name__)

HAND_IOU = 0.05
EDGE_FRAC = 0.02
Phase = Literal["UNTRACKED", "HELD", "PLACED_VISIBLE", "PLACED_GONE", "WITH_YOU"]
_STATE = {"UNTRACKED": "UNKNOWN", "HELD": "HELD", "PLACED_VISIBLE": "PLACED",
          "PLACED_GONE": "PLACED", "WITH_YOU": "CARRIED_OUT"}


@dataclass
class WearObs:
    ts: float
    looked: bool                 # the detector ran this tick
    fresh: bool                  # the camera delivered a new frame
    hands: list[Box]
    cand: Candidate | None       # best-scoring candidate for this item
    accepted: bool               # it passed Identity.accepts
    frame_wh: tuple[int, int]


def _hand_on(box: Box, hands: list[Box]) -> bool:
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    return any(iou(h, box) > HAND_IOU or (h[0] <= cx <= h[2] and h[1] <= cy <= h[3]) for h in hands)


@dataclass
class WearStatus:
    item_id: str
    display_name: str
    phase: str
    unseen_s: float
    last_seen_ts: float | None
    sightings: int


class WearTracker:
    def __init__(self, item_id: str, engine_cfg: EngineCfg, wear_cfg: WearableCfg):
        self.item_id = item_id
        self.ecfg, self.wcfg = engine_cfg, wear_cfg
        self.phase: Phase = "UNTRACKED"
        self.zone: str | None = None
        self.bbox: Box | None = None
        self.live_box: Box | None = None
        self.confidence: float = 0.0
        self.last_placed_ts: float | None = None
        self.last_seen_ts: float | None = None
        self.unseen_s: float = 0.0
        self.sightings: int = 0
        self._touch_since: float | None = None
        self._placed_n = 0
        self._unseen_n = 0
        self._hits: deque[float] = deque()
        self._prev_ts: float | None = None

    @property
    def state(self) -> str:
        return _STATE[self.phase]

    def _ev(self, kind, ts, bbox) -> TrackerEvent:
        return TrackerEvent(kind=kind, item_id=self.item_id, ts=ts, from_zone=None, to_zone=None,
                            bbox=bbox, confidence=self.confidence)

    def _set(self, phase: Phase) -> None:
        if phase != self.phase:
            logger.info("%s: %s -> %s", self.item_id, self.phase, phase)
        self.phase = phase
        self._placed_n = self._unseen_n = 0
        self._hits.clear()

    def step(self, obs: WearObs) -> list[TrackerEvent]:
        ts = obs.ts
        events: list[TrackerEvent] = []
        seen = obs.looked and obs.accepted and obs.cand is not None
        cand = obs.cand if seen else None
        hand = seen and _hand_on(cand.box, obs.hands)

        if self.phase == "PLACED_GONE" and obs.fresh and self._prev_ts is not None:
            self.unseen_s += min(max(ts - self._prev_ts, 0.0), self.wcfg.stale_frame_s)
        self._prev_ts = ts

        if obs.looked and not seen:
            self.live_box = None          # keep it on ticks where the detector did not run
        if seen:
            self.bbox, self.live_box = cand.box, cand.box
            self.confidence, self.last_seen_ts = cand.sim, ts
            if hand:
                if self._touch_since is None:
                    self._touch_since = ts
            else:
                self._touch_since = None
        elif obs.looked:
            self._touch_since = None
        touched = hand and self._touch_since is not None and ts - self._touch_since >= self.wcfg.touch_s

        if self.phase in ("UNTRACKED", "PLACED_VISIBLE", "PLACED_GONE") and touched:
            self._set("HELD")
            events.append(self._ev("PICKED_UP", ts, self.bbox))
            return events

        if self.phase == "HELD":
            # Hand-free sightings since the hand last touched it count toward "put down", with gaps
            # allowed: a moving neck camera matches a just-released item only now and then.
            if obs.looked:
                if seen and not hand:
                    self._placed_n, self._unseen_n = self._placed_n + 1, 0
                elif seen:
                    self._placed_n = self._unseen_n = 0
                else:
                    self._unseen_n += 1
            if seen and not hand and self._placed_n >= self.wcfg.placed_hits:
                self._set("PLACED_VISIBLE")
                self.last_placed_ts = ts
                events.append(self._ev("PLACED", ts, self.bbox))
            elif self._unseen_n >= self.ecfg.missing_frames:
                self._set("WITH_YOU")
                self.unseen_s = 0.0
                events.append(self._ev("CARRIED_OUT", ts, self.bbox))
        elif self.phase == "PLACED_VISIBLE":
            if obs.looked:
                self._unseen_n = 0 if seen else self._unseen_n + 1
            if self._unseen_n >= self.ecfg.missing_frames:
                self._set("PLACED_GONE")
                # Start the timer at the last sighting, not at SEEN (missing_frames ticks later);
                # cap the gap the way per-tick stalls are capped.
                gap = ts - self.last_seen_ts if self.last_seen_ts is not None else 0.0
                self.unseen_s = min(max(gap, 0.0), self.ecfg.missing_frames * self.wcfg.stale_frame_s)
                events.append(self._ev("SEEN", ts, self.bbox))
        elif self.phase in ("PLACED_GONE", "WITH_YOU"):
            if seen:
                self._hits.append(ts)
            while self._hits and ts - self._hits[0] > self.wcfg.seen_again_window_s:
                self._hits.popleft()
            if seen and not hand and len(self._hits) >= self.wcfg.seen_again_hits:
                was = self.phase
                self._set("PLACED_VISIBLE")
                self.sightings += 1
                self.unseen_s = 0.0
                if was == "WITH_YOU":
                    self.last_placed_ts = ts
                    events.append(self._ev("PLACED", ts, self.bbox))
        return events


def frame_score(sim: float, sharpness: float, box: Box, wh: tuple[int, int]) -> float:
    w, h = wh
    area_frac = max(0, box[2] - box[0]) * max(0, box[3] - box[1]) / float(w * h)
    near_edge = (box[0] < EDGE_FRAC * w or box[1] < EDGE_FRAC * h
                 or box[2] > (1 - EDGE_FRAC) * w or box[3] > (1 - EDGE_FRAC) * h)
    return sim * min(1.0, sharpness / 100) * min(1.0, area_frac / 0.01) * (0.5 if near_edge else 1.0)


class BestFrame:
    """Highest-scoring (frame, box) per whole-second bucket over a sliding window."""

    def __init__(self, window_s: float):
        self.window_s = window_s
        self._b: dict[int, tuple[float, np.ndarray, Box, float]] = {}

    def offer(self, ts: float, score: float, frame: np.ndarray, box: Box) -> None:
        k = int(ts)
        cur = self._b.get(k)
        if cur is None or score > cur[0]:
            self._b[k] = (score, frame, box, ts)
        for old in [k2 for k2, v in self._b.items() if ts - v[3] > self.window_s]:
            del self._b[old]

    def best(self, now: float):
        live = [v for v in self._b.values() if now - v[3] <= self.window_s]
        if not live:
            return None
        score, frame, box, _ = max(live, key=lambda v: v[0])
        return frame, box, score

    def clear(self) -> None:
        self._b.clear()
