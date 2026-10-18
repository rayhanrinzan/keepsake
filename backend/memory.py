"""Item memory for a worn camera: when each item was last really seen, and lookups.

The camera moves with the wearer, so a screen position says nothing about where an item is. Memory
therefore keeps only what a sighting does prove: *that* the item was seen, *when*, how confidently,
and whether it is in view right now. Photos and placement evidence come from the observation events
(wearable.py / events.py), which vision.py records with their own photos.

Per category, a detection must hold for `stability` frames within `settle_seconds` before the item
counts as seen (one-frame false hits never do); it is marked out of view after `absence_seconds`.
"""
from __future__ import annotations

import re
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from catalog import ALIASES, BY_CATEGORY, CATALOG, MIN_CONF, SUPPORTED  # noqa: F401  (re-exported)
from database import Database


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
    x: float  # normalized bbox center (in this frame only)
    y: float
    track_id: int | None = None
    bbox: tuple[float, float, float, float] | None = None  # normalized x0,y0,x1,y1
    motion: float = 0.0  # fraction of changed pixels around the object this frame (0..1)


@dataclass
class _Track:
    hits: list[datetime] = field(default_factory=list)  # recent frames with a detection
    last_obs: datetime | None = None


class ItemMemory:
    def __init__(self, db: Database, stability: int = 3, min_confidence: float = 0.35,
                 absence_seconds: float = 2.0, settle_seconds: float = 1.0, **_ignored):
        self.db = db
        self.stability = stability
        self.min_confidence = min_confidence
        self.absence = timedelta(seconds=absence_seconds)
        self.window = timedelta(seconds=settle_seconds)
        self._tracks: dict[str, _Track] = {}
        self._lock = threading.Lock()
        # One camera "view" for the life of the database: kept because the observation event
        # contract (events.py) carries a view_id.
        self.view_id = db.get_setting("view_id") or new_view_id()
        db.set_setting("view_id", self.view_id)

    def observe(self, observations: list[Observation], now: datetime | None = None,
                frame_id: int | None = None) -> list[dict]:
        """Process one frame's detections. Returns `first_seen` events for items seen the first time."""
        now = now or datetime.now(timezone.utc)
        with self._lock:
            best: dict[str, Observation] = {}  # one instance per category: the most confident box
            for o in observations:
                if o.category in ALIASES and o.confidence >= MIN_CONF.get(o.category, self.min_confidence):
                    if o.category not in best or o.confidence > best[o.category].confidence:
                        best[o.category] = o
            events = []
            for category, o in best.items():
                ev = self._update(category, o, now, frame_id)
                if ev:
                    events.append(ev)
            self._mark_absent(set(best), now)
            return events

    def _update(self, category: str, o: Observation, now: datetime, frame_id: int | None) -> dict | None:
        tr = self._tracks.setdefault(category, _Track())
        tr.last_obs = now
        tr.hits = [t for t in tr.hits if now - t <= self.window] + [now]
        rec = self.db.get_by_category(category)
        if len(tr.hits) < self.stability and not (rec and rec["visible"]):
            return None  # not steady enough yet: a single-frame false hit never counts
        first = rec is None
        rec = rec or {"object_id": object_id_for(category), "category": category,
                      "name": display_name(category)}
        rec.update(region=None, x=None, y=None, last_seen=now_iso(now), visible=True,
                   confidence=round(o.confidence, 3), track_id=o.track_id, view_id=self.view_id,
                   lost_while_moving=False)
        self.db.upsert_object(rec)
        if not first:
            return None
        return {"object_id": rec["object_id"], "name": rec["name"], "category": category,
                "event_type": "first_seen", "timestamp": rec["last_seen"], "bbox": o.bbox,
                "confidence": rec["confidence"], "frame_id": frame_id, "view_id": self.view_id}

    def _mark_absent(self, seen: set[str], now: datetime) -> None:
        for rec in self.db.get_objects():
            if not rec["visible"] or rec["category"] in seen:
                continue
            tr = self._tracks.get(rec["category"])
            last = tr.last_obs if tr and tr.last_obs else datetime.fromisoformat(rec["last_seen"])
            if now - last >= self.absence:
                rec["visible"] = False
                self.db.upsert_object(rec)

    def states(self) -> dict[str, str]:
        """Kept for callers that ask whether an item is mid-move: a worn camera can't tell."""
        return {}

    def reset(self) -> None:
        with self._lock:
            self._tracks.clear()
            self.db.clear()


SpatialMemory = ItemMemory  # old name, still imported by teammates' code


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


def answer_query(text: str, lookup, describe=None) -> dict:
    """Grounded answer. `lookup(category)` returns the canonical object view (main.object_view).
    `describe(obj, noun)` may return one sentence about what's around the item in its last photo."""
    parsed = parse_query(text)
    if not parsed:
        names = [c["name"].lower() for c in CATALOG]
        listing = ", ".join(names[:-1]) + f", or {names[-1]}"
        return {"found": False, "object": None, "category": None,
                "answer": f"Sorry, I didn't catch which item you mean. I can look for your {listing}."}
    category, _ = parsed
    noun = display_name(category).lower()
    obj = lookup(category)
    if not obj or not obj.get("seen"):
        return {"found": False, "object": obj, "category": category,
                "answer": f"I haven't seen your {noun} yet."}
    answer = f"I last saw your {noun} {spoken_time(obj['last_seen'])}."
    surroundings = describe(obj, noun) if describe and obj.get("snapshot") else None
    if surroundings:
        answer += f" {surroundings}"
    if obj.get("snapshot"):
        answer += " The last photo is in Keepsake."
    answer += " It's in view right now." if obj.get("visible") else " It may have moved since."
    return {"found": True, "object": obj, "category": category, "answer": answer,
            "surroundings": surroundings}
