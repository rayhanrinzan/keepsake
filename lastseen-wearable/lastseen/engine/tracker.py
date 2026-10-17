"""Per-item state machine: hand-led pick-up / put-down, honest HIDDEN / CARRIED_OUT.

Cardinal rule: a location (bbox/zone) is only ever recorded when the item is set down and still,
never while it is in a hand. The tracker does no I/O; candidates arrive already scored
(`source="stored"` = verification at the stored bbox).

States: UNKNOWN, PLACED, HELD, HIDDEN, CARRIED_OUT. All counts are in ticks.
"""
from __future__ import annotations

import json
import math
from collections import deque

from lastseen.config import EngineCfg, IdentityCfg
from lastseen.engine.zones import ZoneMap
from lastseen.types import Box, Candidate, TickObs, TrackerEvent
from lastseen.vision.geometry import iou
from lastseen.vision.identity import accepts

HAND_IOU = 0.05            # hand "overlaps" a box above this IoU (or box center inside the hand)
FAR_SIM_BONUS = 0.10       # put-down beyond near_hand_px needs sim >= sim_thresh + this ...
FAR_MARGIN = 0.15          # ... and margin >= this
EDGE_FRAC = 0.05           # anchor this close to a frame edge at HELD timeout → CARRIED_OUT
CONF_SURE = 0.9            # PICKED_UP, CARRIED_OUT by holder leaving view
CONF_GUESS = 0.5           # HELD-timeout fallbacks (HIDDEN / CARRIED_OUT at edge)
ANCHOR_HISTORY_S = 2.0     # put-down may be near any holding-hand anchor from the last 2.0 s

LOST_STATES = ("UNKNOWN", "HIDDEN", "CARRIED_OUT")


def _center(b: Box) -> tuple[float, float]:
    return ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)


def _dist(p, q) -> float:
    return math.hypot(p[0] - q[0], p[1] - q[1])


def _inside(pt, b: Box) -> bool:
    return b[0] <= pt[0] <= b[2] and b[1] <= pt[1] <= b[3]


def _hand_overlaps(hand: Box, box: Box) -> bool:
    return iou(hand, box) > HAND_IOU or _inside(_center(box), hand)


def _touches_any_hand(box: Box, hands: list[Box]) -> bool:
    return any(_hand_overlaps(h, box) for h in hands)


def placed_confidence(c: Candidate, change_boxes: list[Box]) -> float:
    """Pinned formula: identity strength + margin + whether the change detector saw something there."""
    change_support = 1.0 if any(iou(cb, c.box) > 0.3 for cb in change_boxes) else 0.0
    v = 0.4 * min(1.0, (c.sim - 0.70) / 0.20) + 0.4 * min(1.0, c.margin / 0.15) + 0.2 * change_support
    return max(0.0, min(1.0, v))


def _parse_bbox(raw) -> Box | None:
    if raw is None:
        return None
    if isinstance(raw, str):
        raw = json.loads(raw)
    return tuple(int(v) for v in raw)  # type: ignore[return-value]


class ItemTracker:
    def __init__(self, item_id: str, engine_cfg: EngineCfg, identity_cfg: IdentityCfg, zones: ZoneMap):
        self.item_id = item_id
        self.ecfg = engine_cfg
        self.icfg = identity_cfg
        self.zones = zones
        self.state: str = "UNKNOWN"
        self.bbox: Box | None = None          # last *placed* box
        self.live_box: Box | None = None      # overlay box: the holding hand while HELD
        self.zone: str | None = None
        self.last_placed_ts: float | None = None
        self.confidence: float = 0.0
        self.holder_track_id: int | None = None
        self._anchor: tuple[int, int] | None = None
        self._anchor_hist: deque[tuple[float, tuple[int, int]]] = deque()  # (ts, anchor), this HELD episode
        self._reset_counters()

    # ------------------------------------------------------------------ public
    def restore(self, item_row: dict) -> None:
        """Load state from a Store item row (bbox as list) or a raw DB row (bbox as JSON string)."""
        self.state = item_row.get("state") or "UNKNOWN"
        self.zone = item_row.get("zone")
        self.bbox = _parse_bbox(item_row.get("bbox"))
        self.confidence = item_row.get("confidence") or 0.0
        self.last_placed_ts = item_row.get("last_placed_ts", item_row.get("last_seen_ts"))
        self.live_box = None
        self.holder_track_id = None
        self._anchor = None
        self._reset_counters()

    def start_held(self, anchor: tuple[int, int], ts: float) -> None:
        """Begin HELD at a hand anchor (an item lifted before it was tracked); bbox/zone are kept."""
        self.state = "HELD"
        self._leave_hand()
        self._anchor = (int(anchor[0]), int(anchor[1]))
        self._remember_anchor(ts)

    def needs_global_search(self) -> bool:
        return self.state in LOST_STATES

    def hand_anchor(self) -> tuple[int, int] | None:
        return self._anchor

    def recent_anchors(self) -> list[tuple[int, int]]:
        """Holding-hand anchors from this HELD episode (last ANCHOR_HISTORY_S), oldest first."""
        return [a for _, a in self._anchor_hist]

    def step(self, obs: TickObs) -> list[TrackerEvent]:
        if self.state == "PLACED":
            ev = self._step_placed(obs)
        elif self.state == "HELD":
            ev = self._step_held(obs)
        else:
            ev = self._step_lost(obs)
        return [ev] if ev is not None else []

    # ------------------------------------------------------------------ counters
    def _reset_counters(self) -> None:
        # PLACED: pick-up arming
        self._arm_n = 0              # consecutive ticks a hand overlaps bbox
        self._armed = False
        self._arm_off_n = 0          # while armed: consecutive ticks with no hand on bbox
        self._arm_verified_n = 0     # while armed: consecutive verified ticks with no hand on bbox
        self._overlap_hand: Box | None = None
        # stillness of a candidate (put-down, moved, reacquire)
        self._still_box: Box | None = None
        self._still_n = 0
        # HELD: consecutive ticks with no hands at all
        self._no_hands_n = 0
        self._anchor_hist = deque()

    def _track_still(self, c: Candidate | None) -> bool:
        """Advance the stillness count with this tick's best candidate; True once still for placed_frames.

        The first sighting counts as 1, so this fires on the placed_frames-th consecutive sighting whose
        center moved < still_px from the previous tick's. A tick with no candidate resets the count."""
        if c is None:
            self._still_box, self._still_n = None, 0
            return False
        if self._still_box is not None and _dist(_center(c.box), _center(self._still_box)) < self.ecfg.still_px:
            self._still_n += 1
        else:
            self._still_n = 1
        self._still_box = c.box
        return self._still_n >= self.ecfg.placed_frames

    # ------------------------------------------------------------------ helpers
    def _accepted(self, c: Candidate) -> bool:
        return accepts(c.sim, c.margin, self.needs_global_search(), self.icfg)

    @staticmethod
    def _best(cands: list[Candidate]) -> Candidate | None:
        return max(cands, key=lambda c: c.sim + c.margin, default=None)

    def _zone_name(self, box: Box, wh) -> str | None:
        z = self.zones.zone_at(box, wh)
        return z.name if z is not None else None

    def _event(self, kind, obs, from_zone, to_zone, bbox, conf) -> TrackerEvent:
        return TrackerEvent(kind=kind, item_id=self.item_id, ts=obs.ts, from_zone=from_zone,
                            to_zone=to_zone, bbox=bbox, confidence=conf)

    def _settle(self, obs: TickObs, c: Candidate) -> TrackerEvent:
        """PLACED / SEEN: the only place bbox and zone are recorded from a sighting."""
        to_zone = self._zone_name(c.box, obs.frame_wh)
        kind = "SEEN" if self.state in LOST_STATES and to_zone == self.zone else "PLACED"
        ev = self._event(kind, obs, self.zone, to_zone, c.box, placed_confidence(c, obs.change_boxes))
        self.state = "PLACED"
        self.bbox, self.zone = c.box, to_zone
        self.last_placed_ts = obs.ts
        self.confidence = ev.confidence
        self._leave_hand()
        return ev

    def _leave_hand(self) -> None:
        self.live_box = None
        self.holder_track_id = None
        self._anchor = None
        self._reset_counters()

    # ------------------------------------------------------------------ PLACED
    def _step_placed(self, obs: TickObs) -> TrackerEvent | None:
        stored = next((c for c in obs.candidates if c.source == "stored"), None)
        verified = stored is not None and self._accepted(stored)
        failed = stored is not None and not verified
        on_bbox = [h for h in obs.hands if _hand_overlaps(h, self.bbox)] if self.bbox else []

        if on_bbox:
            self._arm_n += 1
            self._arm_off_n = 0
            self._overlap_hand = max(on_bbox, key=lambda h: iou(h, self.bbox))
        else:
            self._arm_n = 0
            if self._armed:
                self._arm_off_n += 1
        if self._arm_n >= self.ecfg.held_frames:
            self._armed = True

        if self._armed:
            return self._armed_tick(obs, on_bbox, verified, failed)
        return self._moved_tick(obs)

    def _armed_tick(self, obs, on_bbox, verified, failed) -> TrackerEvent | None:
        # R9.3a: a moved-away sighting counts only if the item is not verified at bbox this tick and the
        # sighting is near the hand that overlapped bbox (a look-alike elsewhere can't fake a pick-up).
        hand_c = _center(self._overlap_hand) if self._overlap_hand is not None else None
        moved_away = not verified and hand_c is not None and any(
            c.source != "stored" and self._accepted(c)
            and _dist(_center(c.box), _center(self.bbox)) >= self.ecfg.move_px
            and _dist(_center(c.box), hand_c) <= self.ecfg.near_hand_px
            for c in obs.candidates)
        # A failed stored check counts only once no hand is on bbox: a resting hand occludes the item,
        # so the lift is confirmed when the hand has moved off the old spot and the item isn't there.
        if (failed and not on_bbox) or moved_away:
            return self._pick_up(obs)
        self._arm_verified_n = self._arm_verified_n + 1 if (verified and not on_bbox) else 0
        if self._arm_off_n >= self.ecfg.missing_frames or self._arm_verified_n >= self.ecfg.held_frames:
            self._reset_counters()  # a brush: hand passed over, item stayed
        return None

    def _pick_up(self, obs: TickObs) -> TrackerEvent:
        ev = self._event("PICKED_UP", obs, self.zone, None, self.bbox, CONF_SURE)
        hand = self._overlap_hand
        self.state = "HELD"
        self.confidence = CONF_SURE
        self._reset_counters()
        self.live_box = hand
        self._anchor = tuple(int(v) for v in _center(hand)) if hand is not None else None
        self._remember_anchor(obs.ts)
        self._update_holder(obs)
        return ev

    def _moved_tick(self, obs: TickObs) -> TrackerEvent | None:
        far = [c for c in obs.candidates
               if c.source != "stored" and self._accepted(c)
               and _dist(_center(c.box), _center(self.bbox)) >= self.ecfg.move_px
               and not _touches_any_hand(c.box, obs.hands)] if self.bbox else []
        best = self._best(far)
        if self._track_still(best):
            return self._settle(obs, best)
        return None

    # ------------------------------------------------------------------ HELD
    def _step_held(self, obs: TickObs) -> TrackerEvent | None:
        if obs.hands:
            self._no_hands_n = 0
            ref = self._anchor
            hand = (min(obs.hands, key=lambda h: _dist(_center(h), ref)) if ref is not None
                    else obs.hands[0])
            self.live_box = hand
            self._anchor = tuple(int(v) for v in _center(hand))
            self._remember_anchor(obs.ts)
        else:
            self._no_hands_n += 1
        self._prune_anchors(obs.ts)

        self._update_holder(obs)
        if self.holder_track_id is not None and self.holder_track_id in obs.left_view:
            return self._lose(obs, "CARRIED_OUT", None, CONF_SURE)

        best = self._best([c for c in obs.candidates if self._putdown_ok(c, obs.hands)])
        if self._track_still(best):
            return self._settle(obs, best)

        if self._no_hands_n >= self.ecfg.missing_frames:
            return self._held_timeout(obs)
        return None

    def _remember_anchor(self, ts: float) -> None:
        if self._anchor is not None:
            self._anchor_hist.append((ts, self._anchor))

    def _prune_anchors(self, now: float) -> None:
        """Drop anchors older than ANCHOR_HISTORY_S, always keeping the latest."""
        while len(self._anchor_hist) > 1 and self._anchor_hist[0][0] < now - ANCHOR_HISTORY_S:
            self._anchor_hist.popleft()

    def _putdown_ok(self, c: Candidate, hands: list[Box]) -> bool:
        if not self._accepted(c) or _touches_any_hand(c.box, hands):
            return False
        cc = _center(c.box)
        if any(_dist(cc, a) <= self.ecfg.near_hand_px for _, a in self._anchor_hist):
            return True
        return c.sim >= self.icfg.sim_thresh + FAR_SIM_BONUS and c.margin >= FAR_MARGIN

    def _update_holder(self, obs: TickObs) -> None:
        if not obs.persons:
            return
        a = self._anchor
        if a is None:
            return
        holder = next((p for p in obs.persons if _inside(a, p.box)), None)
        if holder is None:
            holder = min(obs.persons, key=lambda p: _dist(_center(p.box), a))
        self.holder_track_id = holder.track_id

    def _held_timeout(self, obs: TickObs) -> TrackerEvent | None:
        a = self._anchor
        if a is not None:
            z = self.zones.zone_at_point(a, obs.frame_wh)
            if z is not None and z.type == "cover":
                return self._lose(obs, "HIDDEN", z.name, CONF_GUESS)
            w, h = obs.frame_wh
            if (a[0] <= EDGE_FRAC * w or a[0] >= (1 - EDGE_FRAC) * w
                    or a[1] <= EDGE_FRAC * h or a[1] >= (1 - EDGE_FRAC) * h):
                return self._lose(obs, "CARRIED_OUT", None, CONF_GUESS)
        # Nothing to go on: UNKNOWN, keeping bbox/zone/last_placed_ts from the last PLACED.
        self.state = "UNKNOWN"
        self._leave_hand()
        return None

    def _lose(self, obs: TickObs, kind: str, to_zone: str | None, conf: float) -> TrackerEvent:
        ev = self._event(kind, obs, self.zone, to_zone, self.live_box, conf)
        self.state = kind
        self.zone = to_zone          # where we believe it is now (cover zone, or out of the room)
        self.confidence = conf
        self._leave_hand()
        return ev

    # ------------------------------------------------------------------ UNKNOWN / HIDDEN / CARRIED_OUT
    def _step_lost(self, obs: TickObs) -> TrackerEvent | None:
        # _accepted applies reacquire thresholds here (needs_global_search() is True).
        ok = [c for c in obs.candidates if self._accepted(c) and not _touches_any_hand(c.box, obs.hands)]
        best = self._best(ok)
        if self._track_still(best):
            return self._settle(obs, best)
        return None
