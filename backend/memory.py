"""Spatial memory: turns per-frame detections into settled last-known locations, and answers lookups.

Each tracked category runs a small state machine, advanced once per processed frame (never sleeps):

    STABLE ──displaced──► POSSIBLE_CHANGE ──jump──► MOVING ──holds still──► SETTLING ──► CONFIRMED
       ▲                                                                                   │
       └──────────────────────────── commit location, request snapshot ────────────────────┘

"Displaced" means a different area label (see spatial.locate) than the stored one, or farther than `move_threshold`
(normalized image units) from the stored position. A displaced object must stay within `jitter`
of itself for `settle_seconds` and `stability` frames, with little local motion, to be confirmed.
"""
from __future__ import annotations

import math
import re
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from catalog import ALIASES, BY_CATEGORY, CATALOG, MIN_CONF, SUPPORTED  # noqa: F401  (re-exported)
from database import Database
from spatial import Region, locate, place_phrase

STABLE, POSSIBLE_CHANGE, MOVING, SETTLING = "STABLE", "POSSIBLE_CHANGE", "MOVING", "SETTLING"


def display_name(category: str) -> str:
    return BY_CATEGORY[category]["name"] if category in BY_CATEGORY else category.title()


def object_id_for(category: str) -> str:
    return f"{category.replace(' ', '_')}_01"


def now_iso(now: datetime | None = None) -> str:
    return (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")


def new_view_id() -> str:
    return "view-" + uuid.uuid4().hex[:8]


@dataclass
class Observation:
    category: str
    confidence: float
    x: float  # normalized bbox center
    y: float
    track_id: int | None = None
    bbox: tuple[float, float, float, float] | None = None  # normalized x0,y0,x1,y1
    motion: float = 0.0  # fraction of changed pixels around the object this frame (0..1)


@dataclass
class _Sample:
    t: datetime
    x: float
    y: float
    region: str
    confidence: float
    bbox: tuple[float, float, float, float] | None
    frame_id: int | None
    occluded: bool
    motion: float


@dataclass
class _Track:
    state: str = STABLE
    samples: list[_Sample] = field(default_factory=list)
    last_obs: datetime | None = None


def _covered(box: tuple | None, by: tuple | None) -> float:
    """Fraction of `box` area covered by `by`."""
    if not box or not by:
        return 0.0
    ix = max(0.0, min(box[2], by[2]) - max(box[0], by[0]))
    iy = max(0.0, min(box[3], by[3]) - max(box[1], by[1]))
    area = max(1e-9, (box[2] - box[0]) * (box[3] - box[1]))
    return ix * iy / area


class SpatialMemory:
    def __init__(self, db: Database, regions: list[Region], stability: int = 4,
                 min_confidence: float = 0.4, absence_seconds: float = 2.0,
                 move_threshold: float = 0.06, jitter: float = 0.025,
                 settle_seconds: float = 0.8, motion_threshold: float = 0.08,
                 camera_mode: str = "fixed"):
        self.db = db
        self.regions = regions
        self.stability = stability
        self.min_confidence = min_confidence
        self.absence = timedelta(seconds=absence_seconds)
        self.move_threshold = move_threshold
        self.jitter = jitter
        self.settle = timedelta(seconds=settle_seconds)
        self.motion_threshold = motion_threshold
        # "wearable": the camera moves with the user, so a changed screen position is a new view,
        # not evidence the item moved. Confirmations become `reconfirmed` (no movement event).
        self.camera_mode = camera_mode
        self.loose_categories: set[str] = set()  # categories whose boxes jitter more (custom model)
        self.paused = False
        self._suspended_until: datetime | None = None
        self._tracks: dict[str, _Track] = {}
        self._lock = threading.Lock()
        self.view_id = db.get_setting("view_id") or new_view_id()
        db.set_setting("view_id", self.view_id)
        for rec in db.get_objects():  # records from before view tracking belong to this view
            if rec.get("view_id") is None:
                rec["view_id"] = self.view_id
                db.upsert_object(rec)

    # ---------- per-frame processing ----------
    def observe(self, observations: list[Observation], now: datetime | None = None,
                frame_id: int | None = None) -> list[dict]:
        """Process one frame's detections. Returns confirmed events (each may warrant a snapshot)."""
        now = now or datetime.now(timezone.utc)
        with self._lock:
            if self.paused:
                return []
            if self._suspended_until and now < self._suspended_until:
                for tr in self._tracks.values():
                    tr.samples.clear()
                    tr.state = STABLE
                return []
            people = [o.bbox for o in observations if o.category == "person"]
            # One instance per category: keep the most confident detection of each.
            best: dict[str, Observation] = {}
            for o in observations:
                if o.category in ALIASES and o.confidence >= MIN_CONF.get(o.category, self.min_confidence):
                    if o.category not in best or o.confidence > best[o.category].confidence:
                        best[o.category] = o
            events = []
            for category, o in best.items():
                occluded = any(_covered(o.bbox, p) > 0.6 for p in people)
                ev = self._update(category, o, now, frame_id, occluded)
                if ev:
                    events.append(ev)
            self._mark_absent(set(best), now)
            return events

    def _update(self, category: str, o: Observation, now: datetime, frame_id: int | None,
                occluded: bool) -> dict | None:
        ts = now_iso(now)
        region = locate(o.x, o.y, self.regions)
        rec = self.db.get_by_category(category)
        tr = self._tracks.setdefault(category, _Track())
        tr.last_obs = now
        reacquire = rec is not None and rec.get("view_id") != self.view_id

        if rec:
            rec.update(visible=True, confidence=round(o.confidence, 3), track_id=o.track_id)
        if rec and not reacquire:
            dist = math.hypot(o.x - (rec["x"] or 0), o.y - (rec["y"] or 0))
            displaced = region != rec["region"] or dist > self.move_threshold
        else:
            displaced = True  # first sighting, or first sighting in a new camera view

        if not displaced:  # still where we remember it
            tr.state, tr.samples = STABLE, []
            rec.update(last_seen=ts, lost_while_moving=False)
            self.db.upsert_object(rec)
            return None

        s = _Sample(now, o.x, o.y, region, o.confidence, o.bbox, frame_id, occluded, o.motion)
        last = tr.samples[-1] if tr.samples else None
        jitter = self.jitter * 3 if category in self.loose_categories else self.jitter
        if last and (math.hypot(s.x - last.x, s.y - last.y) > jitter or s.region != last.region):
            tr.state, tr.samples = MOVING, [s]  # still on the move: restart the settle window
        else:
            tr.samples.append(s)
            tr.samples = tr.samples[-60:]
            if tr.state == STABLE:
                tr.state = POSSIBLE_CHANGE
            elif len(tr.samples) >= 2:
                tr.state = SETTLING
        if rec:
            self.db.upsert_object(rec)  # visibility/confidence only; location waits for confirmation

        settled = (len(tr.samples) >= self.stability
                   and now - tr.samples[0].t >= self.settle
                   and s.motion < self.motion_threshold)
        if not settled:
            return None
        return self._confirm(category, rec, tr, ts, reacquire)

    def _confirm(self, category: str, rec: dict | None, tr: _Track, ts: str,
                 reacquire: bool) -> dict:
        cur = tr.samples[-1]
        # Photo frame: the clearest (not covered by a person, most confident) settled frame.
        best = max(tr.samples, key=lambda s: (not s.occluded, s.confidence, s.t))
        if rec is None:
            event_type = "first_seen"
        elif reacquire:
            event_type = "reconfirmed"
        elif cur.region != rec["region"]:
            event_type = "moved"
        else:
            event_type = "moved_within"
        if self.camera_mode == "wearable" and event_type in ("moved", "moved_within"):
            event_type = "reconfirmed"  # see issue #4: no movement claims from a moving camera
        from_region = rec["region"] if rec else None
        rec = rec or {"object_id": object_id_for(category), "category": category,
                      "name": display_name(category), "visible": True,
                      "confidence": round(cur.confidence, 3)}
        rec.update(region=cur.region, x=round(cur.x, 4), y=round(cur.y, 4), last_seen=ts,
                   view_id=self.view_id, lost_while_moving=False, visible=True)
        self.db.upsert_object(rec)
        if event_type != "reconfirmed":  # re-finding an object from a new viewpoint is not a move
            self.db.add_event(rec["object_id"], rec["name"], from_region, cur.region, ts,
                              event_type=event_type, view_id=self.view_id)
        tr.state, tr.samples = STABLE, []
        return {"object_id": rec["object_id"], "name": rec["name"], "category": category,
                "event_type": event_type, "from_region": from_region, "to_region": cur.region,
                "region": cur.region, "timestamp": ts, "bbox": best.bbox,
                "confidence": round(best.confidence, 3), "frame_id": best.frame_id,
                "frame_time": now_iso(best.t),
                "occluded": best.occluded, "view_id": self.view_id}

    def _mark_absent(self, seen: set[str], now: datetime) -> None:
        lost_moving: set[str] = set()
        for category, tr in self._tracks.items():
            if category not in seen and tr.last_obs and now - tr.last_obs >= self.absence:
                if tr.samples:  # left view mid-move: drop the unconfirmed candidate
                    lost_moving.add(category)
                tr.state, tr.samples = STABLE, []
        for rec in self.db.get_objects():
            if not rec["visible"] or rec["category"] in seen:
                continue
            tr = self._tracks.get(rec["category"])
            last = tr.last_obs if tr and tr.last_obs else datetime.fromisoformat(rec["last_seen"])
            if now - last >= self.absence:
                rec["visible"] = False
                rec["lost_while_moving"] = rec["category"] in lost_moving
                self.db.upsert_object(rec)

    # ---------- modes ----------
    def states(self) -> dict[str, str]:
        with self._lock:
            return {c: t.state for c, t in self._tracks.items()}

    def pause(self) -> None:
        with self._lock:
            self.paused = True
            self._tracks.clear()

    def resume(self, new_view: bool = False) -> None:
        """Resume monitoring. With new_view, older memories become 'awaiting reconfirmation'."""
        with self._lock:
            self._tracks.clear()
            self._suspended_until = None
            if new_view:
                self.view_id = new_view_id()
                self.db.set_setting("view_id", self.view_id)
            self.paused = False

    def suspend(self, seconds: float, now: datetime | None = None) -> None:
        """Ignore detections briefly (e.g. the whole camera view shifted)."""
        with self._lock:
            self._suspended_until = (now or datetime.now(timezone.utc)) + timedelta(seconds=seconds)

    def reset(self) -> None:
        with self._lock:
            self._tracks.clear()
            self.db.clear()


# ---------- Natural-language lookup (deterministic alias matching) ----------

def parse_query(text: str) -> tuple[str, str] | None:
    """Return (category, the word the user used) for the longest alias found in text."""
    t = " " + re.sub(r"[^a-z0-9 ]+", " ", text.lower()) + " "
    matches = [(len(a), cat, a) for cat, aliases in ALIASES.items() for a in aliases
               if re.search(rf"\b{re.escape(a)}s?\b", t)]
    if not matches:
        return None
    _, cat, alias = max(matches)
    return cat, alias


def spoken_time(iso: str, now: datetime | None = None) -> str:
    t = datetime.fromisoformat(iso).astimezone()
    clock = t.strftime("%I:%M %p").lstrip("0")
    today = (now or datetime.now(timezone.utc)).astimezone().date()
    if t.date() == today:
        return f"at {clock}"
    if (today - t.date()).days == 1:
        return f"yesterday at {clock}"
    return f"on {t.strftime('%b')} {t.day} at {clock}"


def answer_query(text: str, db: Database, view_id: str | None = None,
                 regions: list[Region] | None = None) -> dict:
    parsed = parse_query(text)
    if not parsed:
        names = [c["name"].lower() for c in CATALOG]
        listing = ", ".join(names[:-1]) + f", or {names[-1]}"
        return {"found": False, "object": None, "snapshot": None, "category": None,
                "answer": f"Sorry, I didn't catch which item you mean. "
                          f"I can look for your {listing}."}
    category, _ = parsed
    noun = display_name(category).lower()
    rec = db.get_by_category(category)
    if not rec or not rec.get("region"):
        return {"found": False, "object": None, "snapshot": None, "category": category,
                "answer": f"I haven't seen your {noun} yet."}
    snaps = db.get_snapshots(rec["object_id"], limit=1)
    answer = f"I last saw your {noun} {place_phrase(rec['region'], regions)} {spoken_time(rec['last_seen'])}"
    if view_id and rec.get("view_id") and rec["view_id"] != view_id:
        answer += ", before the camera was repositioned. I haven't spotted it since."
    elif rec["visible"]:
        answer += ". It's in view right now."
    elif rec.get("lost_while_moving"):
        answer += ". It looked like it was being moved when it left the camera's view."
    else:
        answer += ". It's out of view now, so it may have moved since."
    return {"found": True, "object": rec, "snapshot": snaps[0] if snaps else None,
            "category": category, "answer": answer}
