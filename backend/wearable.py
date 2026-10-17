"""Wearable-camera observation events (issue #4) and hand–object interaction evidence (issue #5).

Pure Python on top of per-frame detections, so it is testable with synthetic sequences and cheap to
run live. Input objects only need `.category`, `.confidence` and `.bbox` (normalized x0,y0,x1,y1), so
`memory.Observation` works as is; hands are `Hand(bbox)` boxes from hands.HandDetector.

Ground rules (from the issues):
* A body-worn camera moves all the time, so screen positions from different moments are NOT compared
  unless the camera was steady the whole time in between. Any burst of camera motion drops partial
  evidence instead of guessing.
* Seeing an item is `object_observed`; it never implies the item moved or was placed.
* `placement_confirmed` is only emitted after a `possible_pickup` for the same item.
* Hand proximity alone is only an `interaction_candidate`.
* Objects are keyed by category (one physical item per category), so tracker ID swaps are irrelevant.
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from catalog import BY_CATEGORY, MIN_CONF
import events as E


@dataclass
class Hand:
    bbox: tuple[float, float, float, float]  # normalized x0, y0, x1, y1
    score: float = 1.0


def _center(b) -> tuple[float, float]:
    return (b[0] + b[2]) / 2, (b[1] + b[3]) / 2


def _size(b) -> float:
    return max(b[2] - b[0], b[3] - b[1])


def _dist(a, b) -> float:
    (ax, ay), (bx, by) = _center(a), _center(b)
    return math.hypot(ax - bx, ay - by)


def touching(hand_box, obj_box, margin: float = 0.25) -> bool:
    """Hand box overlaps the object box grown by `margin` of its size (min 0.02 of the frame)."""
    pad = max(0.02, margin * _size(obj_box))
    x0, y0, x1, y1 = obj_box[0] - pad, obj_box[1] - pad, obj_box[2] + pad, obj_box[3] + pad
    return hand_box[0] < x1 and hand_box[2] > x0 and hand_box[1] < y1 and hand_box[3] > y0


def best_per_category(observations) -> dict:
    """One instance per catalog category: the most confident detection above its min_conf."""
    best: dict = {}
    for o in observations:
        if o.category not in MIN_CONF or o.bbox is None or o.confidence < MIN_CONF[o.category]:
            continue
        if o.category not in best or o.confidence > best[o.category].confidence:
            best[o.category] = o
    return best


def _event(event_type: str, category: str, t: datetime, confidence: float, bbox, evidence,
           camera_mode: str, view_id, frame_id) -> dict:
    item = BY_CATEGORY[category]
    return E.make_event(event_type, object_id=item["object_id"], category=category,
                        name=item["name"], timestamp=t, confidence=min(1.0, max(0.0, confidence)),
                        bbox=bbox, evidence=evidence, camera_mode=camera_mode, view_id=view_id,
                        frame_id=frame_id)


class _FrameGate:
    """Drops duplicate or out-of-order frames (same frame id, or a timestamp that didn't advance)."""

    def __init__(self):
        self._frame_id = None
        self._t = None

    def accept(self, now: datetime, frame_id: int | None) -> bool:
        if frame_id is not None and frame_id == self._frame_id:
            return False
        if self._t is not None and now <= self._t:
            return False
        self._frame_id, self._t = frame_id, now
        return True


# ---------------------------------------------------------------- issue #4: object_observed

@dataclass
class _Hit:
    t: datetime
    confidence: float
    bbox: tuple
    frame_id: int | None


@dataclass
class _Seen:
    frames: deque = field(default_factory=lambda: deque(maxlen=5))  # Optional[_Hit] per steady frame
    present: bool = False
    last_hit: datetime | None = None
    last_emit: datetime | None = None


class WearableObserver:
    """Emits `object_observed` when an item is detected steadily, filtering out:

    * flicker / one-off false hits: needs `min_hits` of the last `window` steady frames, all within
      `position_tolerance` of each other;
    * brief occlusion: an item stays "present" until unseen for `absence_seconds`, so covering it
      for a moment doesn't produce a second sighting;
    * camera motion: frames with camera_motion above `max_camera_motion` neither add nor remove
      evidence (blurred pans cause false boxes);
    * duplicates: at most one event per item per `cooldown_seconds`, and repeated frames are ignored.
    """

    def __init__(self, camera_mode: str = "wearable", window: int = 5, min_hits: int = 3,
                 position_tolerance: float = 0.15, absence_seconds: float = 2.0,
                 cooldown_seconds: float = 30.0, max_camera_motion: float = 0.3):
        self.camera_mode = camera_mode
        self.window, self.min_hits = window, min_hits
        self.position_tolerance = position_tolerance
        self.absence = timedelta(seconds=absence_seconds)
        self.cooldown = timedelta(seconds=cooldown_seconds)
        self.max_camera_motion = max_camera_motion
        self._seen: dict[str, _Seen] = {}
        self._gate = _FrameGate()

    def reset(self) -> None:
        self._seen.clear()

    def update(self, observations, now: datetime, frame_id: int | None = None,
               camera_motion: float = 0.0, view_id: str | None = None) -> list[dict]:
        if not self._gate.accept(now, frame_id):
            return []
        best = best_per_category(observations)
        steady = camera_motion <= self.max_camera_motion
        out = []
        for cat in set(self._seen) | set(best):
            s = self._seen.setdefault(cat, _Seen(frames=deque(maxlen=self.window)))
            o = best.get(cat)
            if o is not None:
                s.last_hit = now  # any sighting keeps the item present, even mid-pan
            if s.present and s.last_hit and now - s.last_hit >= self.absence:
                s.present = False
                s.frames.clear()
            if not steady:
                continue
            s.frames.append(_Hit(now, o.confidence, tuple(o.bbox), frame_id) if o else None)
            if s.present:
                continue
            hits = [h for h in s.frames if h]
            if len(hits) < self.min_hits:
                continue
            if max(_dist(a.bbox, b.bbox) for a in hits for b in hits) > self.position_tolerance:
                continue  # boxes jumping around: likely different false hits
            s.present = True
            if s.last_emit and now - s.last_emit < self.cooldown:
                continue
            s.last_emit = now
            top = max(hits, key=lambda h: h.confidence)
            conf = sum(h.confidence for h in hits) / len(hits)
            out.append(_event(E.OBJECT_OBSERVED, cat, top.t, conf, top.bbox,
                              ["stable_object_detection", "camera_steady"],
                              self.camera_mode, view_id, top.frame_id))
        return out


# ---------------------------------------------------------------- issue #5: hand interactions

IDLE, NEAR, HELD = "IDLE", "NEAR", "HELD"


@dataclass
class _Interaction:
    state: str = IDLE
    anchor: tuple | None = None   # object box while resting untouched (same steady view)
    near: int = 0                 # consecutive frames with a hand on the object
    moved: int = 0                # consecutive touched frames displaced from the anchor
    away: int = 0                 # frames the object stayed missing with no hand on its anchor
    det_conf: float = 0.0
    held_since: datetime | None = None
    settle: list = field(default_factory=list)  # _Hit samples while settling after a pickup


class InteractionDetector:
    """Hand–object evidence: interaction_candidate -> possible_pickup -> placement_confirmed.

    Sequence it looks for (camera steady throughout; any camera motion resets the partial state):
      1. the item rests untouched (its box becomes the anchor);
      2. a hand touches it for `near_frames` frames                    -> interaction_candidate
      3. it moves with the hand (`moved_frames` frames beyond `move_distance` of the anchor), or it
         disappears and stays gone for `gone_frames` frames after the hand left its spot -> possible_pickup
         (if it reappears where it was once the hand leaves, it was only occluded: nothing more)
      4. later it shows up again, untouched and still for `settle_frames` frames -> placement_confirmed
    A possible pickup that is never followed by a placement expires after `hold_seconds` (the item is
    probably being carried).
    """

    def __init__(self, camera_mode: str = "wearable", near_frames: int = 2, moved_frames: int = 2,
                 gone_frames: int = 3, settle_frames: int = 5, move_distance: float = 0.06,
                 reappear_tolerance: float = 0.06, jitter: float = 0.03,
                 max_camera_motion: float = 0.15, hold_seconds: float = 120.0,
                 touch_margin: float = 0.25):
        self.camera_mode = camera_mode
        self.near_frames, self.moved_frames = near_frames, moved_frames
        self.gone_frames, self.settle_frames = gone_frames, settle_frames
        self.move_distance, self.reappear_tolerance = move_distance, reappear_tolerance
        self.jitter = jitter
        self.max_camera_motion = max_camera_motion
        self.hold = timedelta(seconds=hold_seconds)
        self.touch_margin = touch_margin
        self._st: dict[str, _Interaction] = {}
        self._gate = _FrameGate()

    def reset(self) -> None:
        self._st.clear()

    def states(self) -> dict[str, str]:
        return {c: s.state for c, s in self._st.items()}

    def _touch(self, hands, box) -> bool:
        return any(touching(h.bbox, box, self.touch_margin) for h in hands)

    def _moved_beyond(self, box, anchor, base: float) -> bool:
        return _dist(box, anchor) > max(base, 0.5 * _size(anchor))

    def update(self, observations, hands: list[Hand], now: datetime, frame_id: int | None = None,
               camera_motion: float = 0.0, view_id: str | None = None) -> list[dict]:
        if not self._gate.accept(now, frame_id):
            return []
        best = best_per_category(observations)
        steady = camera_motion <= self.max_camera_motion
        out: list[dict] = []
        for cat in set(self._st) | set(best):
            st = self._st.setdefault(cat, _Interaction())
            o = best.get(cat)
            ev = lambda kind, conf, box, evidence: out.append(_event(  # noqa: E731
                kind, cat, now, conf, box, evidence, self.camera_mode, view_id, frame_id))

            if st.state == HELD and now - st.held_since > self.hold:
                self._st[cat] = st = _Interaction()  # carried away: stop waiting for a placement
            if not steady:  # positions before/after a pan aren't comparable
                st.near = st.moved = st.away = 0
                st.settle = []
                if st.state == NEAR:
                    st.state = IDLE
                st.anchor = None
                continue

            on_obj = o is not None and self._touch(hands, o.bbox)

            if st.state == HELD:
                if o is None or on_obj:
                    st.settle = []
                    continue
                if st.settle and _dist(o.bbox, st.settle[-1].bbox) > self.jitter:
                    st.settle = []
                st.settle.append(_Hit(now, o.confidence, tuple(o.bbox), frame_id))
                if len(st.settle) >= self.settle_frames:
                    mean = sum(h.confidence for h in st.settle) / len(st.settle)
                    ev(E.PLACEMENT_CONFIRMED, 0.5 + 0.4 * mean, o.bbox,
                       ["prior_possible_pickup", "hand_released", "stable_object_detection",
                        "camera_steady"])
                    self._st[cat] = _Interaction(anchor=tuple(o.bbox))
                continue

            if st.state == IDLE:
                if o is None:
                    st.near = 0
                elif not on_obj:
                    st.anchor, st.near = tuple(o.bbox), 0
                elif st.anchor is not None:  # a hand on an item we saw resting
                    st.near += 1
                    st.det_conf = o.confidence
                    if st.near >= self.near_frames:
                        st.state, st.moved, st.away = NEAR, 0, 0
                        ev(E.INTERACTION_CANDIDATE, 0.4, o.bbox, ["hand_near_object", "camera_steady"])
                continue

            # NEAR: a hand has been on the item
            if o is not None:
                st.away = 0
                displaced = self._moved_beyond(o.bbox, st.anchor, self.move_distance)
                if on_obj:
                    st.moved = st.moved + 1 if displaced else 0
                    if st.moved >= self.moved_frames:
                        ev(E.POSSIBLE_PICKUP, 0.7, o.bbox,
                           ["hand_near_object", "object_moved_with_hand", "camera_steady"])
                        st.state, st.held_since, st.settle = HELD, now, []
                elif _dist(o.bbox, st.anchor) <= max(self.reappear_tolerance, 0.5 * _size(st.anchor)):
                    self._st[cat] = _Interaction(anchor=tuple(o.bbox))  # touched/occluded, not moved
                else:  # slid to a new spot and the hand already let go
                    ev(E.POSSIBLE_PICKUP, 0.6, o.bbox,
                       ["hand_near_object", "object_moved_with_hand", "camera_steady"])
                    st.state, st.held_since = HELD, now
                    st.settle = [_Hit(now, o.confidence, tuple(o.bbox), frame_id)]
            else:
                if self._touch(hands, st.anchor):
                    st.away = 0  # hand still over the spot: could just be covering it
                else:
                    st.away += 1
                    if st.away >= self.gone_frames:
                        ev(E.POSSIBLE_PICKUP, 0.55, st.anchor,
                           ["hand_near_object", "object_left_with_hand", "camera_steady"])
                        st.state, st.held_since, st.settle = HELD, now, []
        return out
