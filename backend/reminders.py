"""Smart memory reminders: one policy engine, two presets (High-Assistance, Everyday).

Keepsake observations -> per-object reminder state machine -> structured alerts. The Photon
Spectrum agent (integrations/photon) polls the alerts, checks its own recipient allowlist, sends
the text and reports back. Nothing here does network I/O, and it never runs on the camera thread.

Evidence, weakest to strongest (it never claims more than it has):
  object_observed / object_reobserved  a real, photo-backed stable sighting. Not a placement.
  placement_inferred                   fixed camera only: memory saw the item move, then settle.
  placement_confirmed                  from hand-interaction evidence (issue #5), when available.
  interaction_candidate                hand near the item: recorded, never cancels or triggers.
  possible_pickup                      cancels a pending reminder only at pickup_cancel_conf.

Events come from the vision pipeline's `observations` table (backend/events.py, issues #4/#5:
object_observed, interaction_candidate, possible_pickup, placement_confirmed), read by `seq` cursor
on the engine's own thread. With a fixed camera, memory's "moved then settled" photo rows are also
read as placement_inferred. Other producers can POST the same contract or call `ingest()`.

Separation (what makes a pending reminder due):
  wearable    the item has been out of the wearer's view for the mode's delay. A weak signal: it
              says the camera turned away, not that the item stayed behind.
  fixed       a tracked person left the view (departure feed) after the placement.
  either      an explicit check: "I'm heading out" or the manual demo trigger.

This is a hackathon prototype for memory support, not a clinically validated monitoring device.
"""
from __future__ import annotations

import itertools
import json
import logging
import threading
import time
from collections import deque
from datetime import datetime, timezone

from catalog import CATALOG
from departure import hold_reason
from spatial import place_phrase

log = logging.getLogger("keepsake.reminders")

IDLE, OBSERVED, POSSIBLE_INTERACTION = "IDLE", "OBSERVED", "POSSIBLE_INTERACTION"
PLACEMENT_CANDIDATE, PENDING_REMINDER = "PLACEMENT_CANDIDATE", "PENDING_REMINDER"
REMINDER_SENT, CANCELLED = "REMINDER_SENT", "CANCELLED"

EVENT_TYPES = ("object_observed", "object_reobserved", "interaction_candidate", "possible_pickup",
               "placement_confirmed", "placement_inferred")
OBSERVATION = ("object_observed", "object_reobserved")
PLACEMENT = ("placement_confirmed", "placement_inferred")
MODES = ("off", "high_assistance", "everyday")
SETTINGS_KEY = "reminder_settings"

# Shared engine, two presets. Times in seconds.
PRESETS: dict[str, dict] = {
    "high_assistance": {
        "delay": 15,                    # out of view this long after the sighting/placement
        "triggers": ["placement_confirmed", "placement_inferred", "object_observed",
                     "interaction_then_stable"],
        "min_confidence": 0.45,
        "per_item_cooldown": 300,
        "global_cooldown": 60,
        "max_photo_age": 1800,          # photo must be at most this old when the reminder goes out
        "max_pending": 900,             # give up on a pending reminder after this long
        "pickup_cancel_conf": 0.55,     # events.py pickups: 0.55 (left with hand) .. 0.7 (moved with it)
        "snooze": 600,
        "tone": "gentle",
    },
    "everyday": {
        "delay": 150,
        "triggers": ["placement_confirmed", "placement_inferred"],
        "min_confidence": 0.6,
        "per_item_cooldown": 1800,
        "global_cooldown": 600,
        "max_photo_age": 7200,
        "max_pending": 1800,
        "pickup_cancel_conf": 0.55,
        "snooze": 900,
        "tone": "heading_out",
    },
}
DEFAULT_SETTINGS = {
    "enabled": False,        # nothing is queued until someone explicitly opts in
    "mode": "off",
    "opted_in_at": None,
    "important": ["keys", "wallet", "phone"],  # names/aliases; resolved against the catalog
    "overrides": {"high_assistance": {}, "everyday": {}},
    "paused_until": None,    # epoch seconds; float("inf") is stored as -1 (paused until resumed)
}
INTERACTION_WINDOW = 60      # an observation this soon after an interaction is a placement candidate
PHOTO_WAIT = 15              # a placement whose photo hasn't arrived by then is dropped
CLAIM_TIMEOUT = 60           # a claimed alert with no result after this is "unknown", never resent
QUEUE_TIMEOUT = 120          # a queued alert nobody picked up (agent offline) expires
RETRY_DELAY = 20
MAX_ATTEMPTS = 2
OVERRIDABLE = {"delay", "min_confidence", "per_item_cooldown", "global_cooldown", "max_photo_age",
               "max_pending", "pickup_cancel_conf", "snooze"}


def _ts(iso: str | None) -> float | None:
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).timestamp()


def _iso(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).isoformat(timespec="seconds")


class EventError(ValueError):
    pass


class _Obj:
    """Reminder state for one catalog item."""

    def __init__(self, object_id: str):
        self.object_id = object_id
        self.state = IDLE
        self.episode: str | None = None       # placement/observation id the reminder belongs to
        self.evidence: str | None = None      # trigger kind for the current episode
        self.confidence: float | None = None
        self.started: float | None = None     # when the episode's placement/sighting happened
        self.snapshot_id: int | None = None
        self.interaction_at: float | None = None
        self.alert_id: int | None = None
        self.reason: str | None = None        # why it was cancelled
        self.due_at: float | None = None      # snoozed reminders: not before this

    def view(self) -> dict:
        return {"state": self.state, "episode": self.episode, "evidence": self.evidence,
                "confidence": self.confidence, "started": _iso(self.started) if self.started else None,
                "snapshot_id": self.snapshot_id, "alert_id": self.alert_id, "reason": self.reason}


class ReminderEngine:
    def __init__(self, db, memory=None, modes=None, regions=None, departures=None,
                 status_fn=None, clock=time.time, camera_mode: str = "wearable"):
        self.db = db
        self.camera_mode = "fixed" if camera_mode in ("fixed", "stationary") else "wearable"  # CTRLF_CAMERA_MODE
        self.memory = memory
        self.modes = modes
        self.regions = regions if regions is not None else []
        self.departures = departures      # DepartureFeed (fixed camera separation signal)
        self.status_fn = status_fn or (lambda: {})
        self.clock = clock
        self.items = {c["object_id"]: c for c in CATALOG}
        self.by_category = {c["category"]: c["object_id"] for c in CATALOG}
        self.settings = self._load_settings()
        self._objs: dict[str, _Obj] = {oid: _Obj(oid) for oid in self.items}
        self._seen_events: deque[str] = deque(maxlen=2000)
        self._seen_set: set[str] = set()
        self._inbox: deque[dict] = deque(maxlen=500)   # events from other threads (ingest())
        self._alerts: dict[int, dict] = {}
        self._alert_ids = itertools.count(1)
        self._last_alerted: dict[str, float] = {}
        self._last_alert_at = float("-inf")
        self._snapshot_cursor = self._max_snapshot_id()   # only react to evidence from now on
        self._observation_cursor = self._max_observation_seq()
        self._departure_cursor = departures.latest_id() if departures else 0
        self._departure_at = float("-inf")
        self.log: deque[dict] = deque(maxlen=200)         # diagnostics, no message text
        self._lock = threading.RLock()
        self._halt = threading.Event()
        self._thread: threading.Thread | None = None

    # ---------- settings ----------
    def _load_settings(self) -> dict:
        s = json.loads(json.dumps(DEFAULT_SETTINGS))
        raw = self.db.get_setting(SETTINGS_KEY)
        if raw:
            try:
                s.update(json.loads(raw))
            except ValueError:
                log.warning("unreadable reminder settings; using defaults")
        s.pop("camera_mode", None)  # now CTRLF_CAMERA_MODE, shared with the vision pipeline
        return s

    def _save_settings(self) -> None:
        self.db.set_setting(SETTINGS_KEY, json.dumps(self.settings))

    def policy(self, mode: str | None = None) -> dict | None:
        mode = mode or self.settings["mode"]
        if mode not in PRESETS:
            return None
        return {**PRESETS[mode], **self.settings["overrides"].get(mode, {}), "mode": mode}

    def update_settings(self, changes: dict, opt_in: bool = False) -> dict:
        """Apply a settings change. Turning reminders on requires an explicit opt-in."""
        with self._lock:
            new = json.loads(json.dumps(self.settings))
            if "mode" in changes:
                if changes["mode"] not in MODES:
                    raise ValueError(f"mode must be one of {', '.join(MODES)}")
                new["mode"] = changes["mode"]
            if "enabled" in changes:
                new["enabled"] = bool(changes["enabled"])
            if "important" in changes:
                important = []
                for name in changes["important"]:
                    oid = self._resolve(name)
                    if oid is None:
                        raise ValueError(f"Keepsake doesn't track {name!r}")
                    important.append(self.items[oid]["name"].lower())
                new["important"] = list(dict.fromkeys(important))
            for mode, vals in (changes.get("overrides") or {}).items():
                if mode not in PRESETS:
                    raise ValueError(f"no preset {mode!r}")
                bad = set(vals) - OVERRIDABLE
                if bad:
                    raise ValueError(f"can't override {', '.join(sorted(bad))}")
                if any(not isinstance(v, (int, float)) or v < 0 for v in vals.values()):
                    raise ValueError("overrides must be non-negative numbers")
                new["overrides"][mode] = {**new["overrides"].get(mode, {}), **vals}
            turning_on = new["enabled"] and new["mode"] != "off"
            was_on = self.settings["enabled"] and self.settings["mode"] != "off"
            if turning_on and not was_on and not opt_in:
                raise PermissionError("Turning reminders on needs an explicit opt-in (opt_in: true)")
            if turning_on and not was_on:
                new["opted_in_at"] = _iso(self.clock())
            mode_changed = new["mode"] != self.settings["mode"] or new["enabled"] != self.settings["enabled"]
            self.settings = new
            self._save_settings()
            if mode_changed:
                self._cancel_all("mode_changed")
            return self.status()

    def important(self) -> list[str]:
        """Watched object_ids. Entries are catalog names/aliases, so catalog edits can't break them;
        anything the catalog no longer tracks is skipped."""
        out = []
        for name in self.settings["important"]:
            oid = self._resolve(name)
            if oid and oid not in out:
                out.append(oid)
        return out

    def active(self) -> bool:
        return bool(self.settings["enabled"]) and self.settings["mode"] in PRESETS

    def paused(self, now: float) -> bool:
        p = self.settings.get("paused_until")
        return p is not None and (p == -1 or now < p)

    def pause(self, seconds: float | None = None) -> None:
        with self._lock:
            self.settings["paused_until"] = -1 if seconds is None else self.clock() + seconds
            self._save_settings()
            self._cancel_all("paused")

    def resume(self) -> None:
        with self._lock:
            self.settings["paused_until"] = None
            self._save_settings()

    # ---------- events ----------
    def _resolve(self, ident: str | None) -> str | None:
        if not ident:
            return None
        ident = str(ident).strip().lower()
        if ident in self.items:
            return ident
        if ident in self.by_category:
            return self.by_category[ident]
        for c in CATALOG:
            if ident == c["name"].lower() or ident in (a.lower() for a in c["aliases"]):
                return c["object_id"]
        return None

    def normalize(self, raw: dict) -> dict:
        """Validate an event against the contract (EVENTS.md). Raises EventError."""
        etype = raw.get("event_type")
        if etype not in EVENT_TYPES or etype == "placement_inferred":
            raise EventError(f"event_type must be one of {', '.join(t for t in EVENT_TYPES if t != 'placement_inferred')}")
        if not raw.get("event_id"):
            raise EventError("event_id is required")
        oid = self._resolve(raw.get("object_id") or raw.get("category"))
        if oid is None:
            raise EventError("unknown object_id/category")
        t = _ts(raw.get("timestamp"))
        if t is None:
            raise EventError("timestamp must be ISO-8601")
        conf = raw.get("confidence")
        if not isinstance(conf, (int, float)) or not 0 <= conf <= 1:
            raise EventError("confidence must be a number from 0 to 1")
        snap = raw.get("snapshot_id")
        if snap is not None and not isinstance(snap, int):
            raise EventError("snapshot_id must be an integer or null")
        return {"event_id": str(raw["event_id"]), "event_type": etype, "object_id": oid, "t": t,
                "confidence": float(conf), "snapshot_id": snap,
                "evidence": [str(e) for e in raw.get("evidence") or []][:10],
                "camera_mode": raw.get("camera_mode"), "view_id": raw.get("view_id"),
                "source": raw.get("source") or "external"}

    def ingest(self, raw: dict) -> None:
        """Thread-safe, non-blocking hand-off for in-process producers (e.g. hand tracking)."""
        self._inbox.append(raw)

    def submit(self, raw: dict) -> dict:
        """Validate and apply one event now (HTTP intake). Returns what happened."""
        ev = self.normalize(raw)
        with self._lock:
            return self._apply(ev, self.clock())

    def _duplicate(self, event_id: str) -> bool:
        if event_id in self._seen_set:
            return True
        if len(self._seen_events) == self._seen_events.maxlen:
            self._seen_set.discard(self._seen_events[0])
        self._seen_events.append(event_id)
        self._seen_set.add(event_id)
        return False

    def _note(self, what: str, **kw) -> None:
        self.log.append({"at": _iso(self.clock()), "what": what, **kw})

    def _apply(self, ev: dict, now: float) -> dict:
        if self._duplicate(ev["event_id"]):
            return {"result": "duplicate"}
        o = self._objs[ev["object_id"]]
        etype, policy = ev["event_type"], self.policy()
        watched = self.active() and ev["object_id"] in self.important() and not self.paused(now)

        if etype == "interaction_candidate":
            o.interaction_at = ev["t"]
            if o.state not in (PENDING_REMINDER, PLACEMENT_CANDIDATE):
                o.state = POSSIBLE_INTERACTION
            return {"result": "recorded", "state": o.state}  # hand proximity is not contact

        if etype == "possible_pickup":
            o.interaction_at = ev["t"]
            strong = policy is not None and ev["confidence"] >= policy["pickup_cancel_conf"]
            if strong and o.state in (PENDING_REMINDER, PLACEMENT_CANDIDATE):
                self._cancel(o, "picked_up")
                return {"result": "cancelled", "state": o.state}
            if o.state not in (PENDING_REMINDER, PLACEMENT_CANDIDATE):
                o.state = POSSIBLE_INTERACTION
            return {"result": "recorded", "state": o.state}

        # Observations and placements. A snapshot id only counts if that photo really exists.
        snap = ev["snapshot_id"]
        if snap is not None:
            row = self.db.get_snapshot(snap)
            snap = snap if row and row["object_id"] == ev["object_id"] else None
        if snap is not None:
            o.snapshot_id = snap
        kind = etype
        if etype in OBSERVATION and o.interaction_at and 0 <= ev["t"] - o.interaction_at <= INTERACTION_WINDOW:
            kind = "interaction_then_stable"  # a hand was near it, then it was seen stable
        if o.state in (PENDING_REMINDER, PLACEMENT_CANDIDATE) and etype in OBSERVATION:
            # Same item seen again: newest photo grounds the reminder; the timer is not reset.
            return {"result": "updated", "state": o.state}
        if not watched or policy is None:
            if o.state not in (REMINDER_SENT,):
                o.state = OBSERVED
            return {"result": "observed", "state": o.state, "why": "not_watched"}
        if kind not in policy["triggers"]:
            o.state = OBSERVED if o.state != REMINDER_SENT else o.state
            return {"result": "observed", "state": o.state, "why": "evidence_not_enough_for_mode"}
        if ev["confidence"] < policy["min_confidence"]:
            o.state = OBSERVED if o.state != REMINDER_SENT else o.state
            return {"result": "observed", "state": o.state, "why": "low_confidence"}
        last = self._last_alerted.get(o.object_id)
        if etype in OBSERVATION and o.state == REMINDER_SENT and last is not None \
                and now - last < policy["per_item_cooldown"]:
            return {"result": "observed", "state": o.state, "why": "already_reminded"}
        if o.state in (PENDING_REMINDER, PLACEMENT_CANDIDATE):
            self._cancel(o, "superseded")  # a newer placement replaces the old one
        o.state, o.episode, o.evidence = PLACEMENT_CANDIDATE, ev["event_id"], kind
        o.confidence, o.started, o.alert_id, o.reason, o.due_at = ev["confidence"], ev["t"], None, None, None
        o.interaction_at, o.snapshot_id = None, snap  # this episode's own photo, or wait for one
        if snap is not None:
            o.state = PENDING_REMINDER
        self._note("pending" if o.state == PENDING_REMINDER else "candidate",
                   object_id=o.object_id, evidence=kind, episode=o.episode)
        return {"result": "scheduled" if o.state == PENDING_REMINDER else "candidate", "state": o.state}

    def _cancel(self, o: _Obj, reason: str) -> None:
        o.state, o.reason, o.alert_id = CANCELLED, reason, None
        self._note("cancelled", object_id=o.object_id, reason=reason, episode=o.episode)

    def _cancel_all(self, reason: str) -> None:
        for o in self._objs.values():
            if o.state in (PENDING_REMINDER, PLACEMENT_CANDIDATE):
                self._cancel(o, reason)
        for a in self._alerts.values():
            if a["status"] == "queued":
                a["status"] = "cancelled"
                a["reason"] = reason

    # ---------- memory feed ----------
    def _max_snapshot_id(self) -> int:
        with self.db._lock:
            row = self.db._conn.execute("SELECT MAX(id) AS m FROM snapshots").fetchone()
        return row["m"] or 0

    def _new_snapshots(self) -> list[dict]:
        with self.db._lock:
            rows = self.db._conn.execute(
                "SELECT * FROM snapshots WHERE id > ? ORDER BY id LIMIT 200",
                (self._snapshot_cursor,)).fetchall()
        rows = [dict(r) for r in rows]
        if rows:
            self._snapshot_cursor = rows[-1]["id"]
        return rows

    def _from_snapshot(self, s: dict) -> dict | None:
        """Fixed camera only: memory's "moved, then settled" photo as placement_inferred.

        Plain sightings come from the observations table instead, so nothing is counted twice."""
        if self.camera_mode != "fixed" or s["event_type"] not in ("moved", "moved_within"):
            return None
        return {"event_id": f"snapshot:{s['id']}", "event_type": "placement_inferred",
                "object_id": s["object_id"], "t": _ts(s["timestamp"]) or self.clock(),
                "confidence": s["confidence"] or 0.0, "snapshot_id": s["id"],
                "evidence": [f"memory_{s['event_type']}"], "camera_mode": "fixed",
                "view_id": s.get("view_id"), "source": "memory"}

    def _max_observation_seq(self) -> int:
        if not hasattr(self.db, "get_observations"):
            return 0
        newest = self.db.get_observations(limit=1)
        return newest[0]["seq"] if newest else 0

    def _new_observations(self) -> list[dict]:
        """Vision pipeline events (backend/events.py contract), oldest first."""
        if not hasattr(self.db, "get_observations"):
            return []
        rows = list(reversed(self.db.get_observations(limit=200, after_seq=self._observation_cursor)))
        if rows:
            self._observation_cursor = rows[-1]["seq"]
        return [{**r, "source": "observations"} for r in rows]

    # ---------- per tick ----------
    def tick(self, now: float | None = None) -> list[dict]:
        """Advance timers. Returns alerts queued on this tick."""
        now = self.clock() if now is None else now
        with self._lock:
            while self._inbox:
                raw = self._inbox.popleft()
                try:
                    self._apply(self.normalize(raw), now)
                except EventError as e:
                    log.warning("rejected reminder event: %s", e)
            for raw in self._new_observations():
                try:
                    self._apply(self.normalize(raw), now)
                except EventError as e:
                    log.warning("skipped observation %s: %s", raw.get("event_id"), e)
            for s in self._new_snapshots():
                ev = self._from_snapshot(s) if s["object_id"] in self._objs else None
                if ev:
                    self._apply(ev, now)
            status = self.status_fn() or {}
            hold = hold_reason(self.modes, self.memory, status, now=now) if self.modes else None
            self._read_departures(status, hold)
            self._expire_alerts(now)
            if not self.active() or self.paused(now):
                return []
            return self._evaluate(now, hold)

    def _read_departures(self, status: dict, hold: str | None) -> None:
        if not self.departures:
            return
        if self.memory is not None:
            self.departures.sync(status, hold, getattr(self.memory, "view_id", None))
        for ev in self.departures.events_after(self._departure_cursor):
            self._departure_cursor = ev["id"]
            if ev["source"] != "manual":
                self._departure_at = _ts(ev["at"]) or self.clock()

    def _object(self, object_id: str) -> dict | None:
        return self.db.get_by_category(self.items[object_id]["category"])

    def _photo(self, o: _Obj, rec: dict | None = None) -> dict | None:
        """The newest real photo of the item (the reminder's grounding)."""
        snaps = self.db.get_snapshots(o.object_id, limit=1)
        return snaps[0] if snaps else None

    def _view_ok(self, rec: dict) -> bool:
        return self.memory is None or rec.get("view_id") in (None, getattr(self.memory, "view_id", None))

    def _place(self, rec: dict | None) -> str | None:
        """A location phrase only when the memory supports it (fixed camera, current view)."""
        if (self.camera_mode != "fixed" or not rec or not rec.get("region")
                or not self._view_ok(rec)):
            return None
        return place_phrase(rec["region"], self.regions)

    def _blocked(self, o: _Obj, rec: dict | None, photo: dict | None, policy: dict, now: float,
                 hold: str | None) -> str | None:
        """Why a pending reminder must be cancelled now (None = still fine)."""
        fixed = self.camera_mode == "fixed"
        if hold in ("camera_repositioning", "camera_unavailable", "camera_dark"):
            return hold
        if hold == "camera_shift" and fixed:
            return "camera_shift"  # wearable cameras move all the time; that's not unreliability
        if rec is None or not rec.get("last_seen"):
            return "no_memory"
        if rec.get("lost_while_moving"):
            return "lost_while_moving"  # seen being moved out of view: likely carried
        if fixed and not self._view_ok(rec):
            return "location_unreliable"
        if photo is None:
            return "no_photo"
        if now - (_ts(photo["timestamp"]) or 0) > policy["max_photo_age"]:
            return "stale_photo"
        if o.started is not None and now - o.started > policy["max_pending"]:
            return "expired"
        return None

    def _due(self, o: _Obj, rec: dict, policy: dict, now: float) -> bool:
        if o.due_at is not None and now < o.due_at:
            return False
        if now - o.started < policy["delay"]:
            return False
        if self.camera_mode == "fixed":
            return self._departure_at > o.started  # someone left after it was put down
        last_seen = _ts(rec["last_seen"]) or now
        return not rec.get("visible") and now - last_seen >= policy["delay"]

    def _evaluate(self, now: float, hold: str | None) -> list[dict]:
        policy = self.policy()
        due = []
        for o in self._objs.values():
            if o.state == PLACEMENT_CANDIDATE:
                if o.snapshot_id is None:
                    photo = self._photo(o, None)
                    if photo and (_ts(photo["timestamp"]) or 0) >= (o.started or 0) - 5:
                        o.snapshot_id = photo["id"]
                if o.snapshot_id is not None:
                    o.state = PENDING_REMINDER
                elif now - (o.started or now) > PHOTO_WAIT:
                    self._cancel(o, "no_photo")
                    continue
                else:
                    continue
            if o.state != PENDING_REMINDER or o.alert_id is not None:
                continue
            rec = self._object(o.object_id)
            photo = self._photo(o, rec)
            why = self._blocked(o, rec, photo, policy, now, hold)
            if why:
                self._cancel(o, why)
                continue
            if not self._due(o, rec, policy, now):
                continue
            last = self._last_alerted.get(o.object_id)
            if last is not None and now - last < policy["per_item_cooldown"]:
                self._cancel(o, "cooldown")
                continue
            due.append((o, rec, photo))
        if not due or now - self._last_alert_at < policy["global_cooldown"]:
            return []  # wait out the global cooldown; max_pending still bounds the wait
        return [self._queue([(o, rec, photo) for o, rec, photo in due], "automatic", now)]

    # ---------- explicit checks ----------
    def check(self, reason: str = "manual") -> dict:
        """Explicit check ("I'm heading out" or the developer trigger) over real stored memory.

        Counts as the separation signal, so the delay is skipped; every other rule still applies.
        Diagnostics label it as manual: it never pretends a placement was detected."""
        if reason not in ("manual", "heading_out"):
            raise ValueError("reason must be manual or heading_out")
        now = self.clock()
        with self._lock:
            if not self.active():
                return {"queued": False, "blocked": "reminders_off", "items": [], "skipped": []}
            if self.paused(now):
                return {"queued": False, "blocked": "paused", "items": [], "skipped": []}
            policy = self.policy()
            status = self.status_fn() or {}
            hold = hold_reason(self.modes, self.memory, status, now=now) if self.modes else None
            picked, skipped = [], []
            for oid in self.important():
                category = self.items[oid]["category"]
                o, rec = self._objs[oid], self._object(oid)
                photo = self._photo(o, rec)
                tmp = _Obj(oid)
                tmp.started = now  # an explicit check has no placement age
                why = self._blocked(tmp, rec, photo, policy, now, hold)
                if why is None and self.memory is not None \
                        and self.memory.states().get(category, "STABLE") != "STABLE":
                    why = "moving"  # mid-move: its location isn't settled
                last = self._last_alerted.get(oid)
                if why is None and last is not None and now - last < policy["per_item_cooldown"]:
                    why = "cooldown"
                if why is None and o.alert_id is not None:
                    why = "already_queued"
                if why:
                    skipped.append({"object_id": oid, "reason": why})
                    continue
                o.evidence = o.evidence if o.state == PENDING_REMINDER else "stored_observation"
                picked.append((o, rec, photo))
            if not picked:
                return {"queued": False, "blocked": "no_eligible_items", "items": [], "skipped": skipped}
            alert = self._queue(picked, reason, now)
            return {"queued": True, "alert": alert, "skipped": skipped}

    # ---------- alerts ----------
    def _queue(self, picked: list, trigger: str, now: float) -> dict:
        policy = self.policy()
        alert = {"id": next(self._alert_ids), "created_at": _iso(now), "trigger": trigger,
                 "mode": policy["mode"], "tone": policy["tone"], "status": "queued",
                 "attempts": 0, "not_before": now, "claimed_at": None, "reason": None,
                 "items": []}
        for o, rec, photo in picked:
            o.alert_id = alert["id"]
            if o.state != PENDING_REMINDER:  # explicit check on an item with no pending episode
                o.state, o.episode, o.started = PENDING_REMINDER, f"{trigger}:{alert['id']}", now
            alert["items"].append({
                "object_id": o.object_id, "name": self.items[o.object_id]["name"],
                "last_seen": rec["last_seen"], "photo_at": photo["timestamp"] if photo else None,
                "snapshot_id": photo["id"] if photo else None,
                "place": self._place(rec), "evidence": o.evidence or "stored_observation",
                "episode": o.episode})
        self._alerts[alert["id"]] = alert
        self._last_alert_at = now  # global cooldown starts when an alert is queued
        self._note("queued", alert_id=alert["id"], trigger=trigger,
                   items=[i["object_id"] for i in alert["items"]])
        log.info("reminder %s queued (%s): %s", alert["id"], trigger,
                 ", ".join(i["name"] for i in alert["items"]))
        return self._public(alert)

    @staticmethod
    def _public(a: dict) -> dict:
        return {k: a[k] for k in ("id", "created_at", "trigger", "mode", "tone", "status",
                                  "attempts", "reason", "items")}

    def alerts(self, status: str | None = "queued") -> list[dict]:
        now = self.clock()
        with self._lock:
            self._expire_alerts(now)
            return [self._public(a) for a in self._alerts.values()
                    if (status is None or a["status"] == status) and a["not_before"] <= now]

    def claim(self, alert_id: int) -> dict:
        """The agent takes an alert before sending, so it can never be sent twice."""
        with self._lock:
            a = self._alerts.get(alert_id)
            if a is None:
                raise KeyError(alert_id)
            if a["status"] != "queued" or a["not_before"] > self.clock():
                raise PermissionError(f"alert {alert_id} is {a['status']}")
            # Re-check: the user may have acknowledged or the mode may have changed meanwhile.
            if not self.active() or self.paused(self.clock()):
                a["status"], a["reason"] = "cancelled", "reminders_off"
                raise PermissionError(f"alert {alert_id} cancelled")
            a["status"], a["claimed_at"] = "sending", self.clock()
            a["attempts"] += 1
            return self._public(a)

    def report(self, alert_id: int, status: str, error: str | None = None) -> dict:
        """Delivery result from the agent: accepted (Spectrum took it) or failed."""
        if status not in ("accepted", "failed"):
            raise ValueError("status must be accepted or failed")
        now = self.clock()
        with self._lock:
            a = self._alerts.get(alert_id)
            if a is None:
                raise KeyError(alert_id)
            if a["status"] != "sending":
                raise PermissionError(f"alert {alert_id} is {a['status']}")
            objs = [self._objs[i["object_id"]] for i in a["items"]]
            if status == "accepted":
                a["status"] = "accepted"
                for o in objs:
                    o.state, o.reason = REMINDER_SENT, None
                    self._last_alerted[o.object_id] = now
                self._note("accepted", alert_id=alert_id)
            elif a["attempts"] < MAX_ATTEMPTS:
                a["status"], a["not_before"], a["reason"] = "queued", now + RETRY_DELAY, (error or "")[:200]
                self._note("retry", alert_id=alert_id)
            else:
                a["status"], a["reason"] = "failed", (error or "")[:200]
                for o in objs:
                    self._cancel(o, "delivery_failed")
                self._note("failed", alert_id=alert_id)
            return self._public(a)

    def _expire_alerts(self, now: float) -> None:
        for a in self._alerts.values():
            if a["status"] == "sending" and now - (a["claimed_at"] or now) > CLAIM_TIMEOUT:
                a["status"], a["reason"] = "unknown", "no result from agent"  # never resent
            elif a["status"] == "queued" and now - (_ts(a["created_at"]) or now) > QUEUE_TIMEOUT:
                a["status"], a["reason"] = "expired", "agent offline"
                for i in a["items"]:
                    o = self._objs[i["object_id"]]
                    if o.alert_id == a["id"]:
                        self._cancel(o, "delivery_unavailable")
        if len(self._alerts) > 200:
            for k in sorted(self._alerts)[:-200]:
                del self._alerts[k]

    def acknowledge(self, action: str, alert_id: int | None = None) -> dict:
        """User replies: have_it (dismiss), snooze (remind later), pause, resume."""
        now = self.clock()
        with self._lock:
            if action == "pause":
                self.pause()
                return {"ok": True, "paused": True}
            if action == "resume":
                self.resume()
                return {"ok": True, "paused": False}
            if action not in ("have_it", "snooze"):
                raise ValueError("action must be have_it, snooze, pause or resume")
            a = self._alerts.get(alert_id) if alert_id else self._latest_delivered()
            if a is None:
                return {"ok": False, "why": "no_recent_reminder"}
            policy = self.policy() or PRESETS["high_assistance"]
            for i in a["items"]:
                o = self._objs[i["object_id"]]
                if action == "have_it":
                    if o.state in (PENDING_REMINDER, PLACEMENT_CANDIDATE, REMINDER_SENT):
                        self._cancel(o, "acknowledged")
                else:  # snooze: one more reminder about the same items later
                    o.state, o.alert_id, o.due_at, o.reason = PENDING_REMINDER, None, now + policy["snooze"], None
                    o.started = now
                    self._last_alerted.pop(o.object_id, None)
            self._note(action, alert_id=a["id"])
            return {"ok": True, "alert_id": a["id"], "action": action}

    def _latest_delivered(self) -> dict | None:
        done = [a for a in self._alerts.values() if a["status"] == "accepted"]
        return max(done, key=lambda a: a["id"]) if done else None

    # ---------- status / thread ----------
    def status(self) -> dict:
        now = self.clock()
        with self._lock:
            p = self.settings.get("paused_until")
            return {"settings": {**self.settings, "camera_mode": self.camera_mode,
                                 "paused_until": None if p in (None, -1) else _iso(p),
                                 "paused": self.paused(now)},
                    "policy": self.policy(), "active": self.active(),
                    "objects": {oid: o.view() for oid, o in self._objs.items()
                                if oid in self.important() or o.state != IDLE},
                    "recent": list(self.log)[-20:]}

    def start(self, interval: float = 1.0) -> None:
        def run():
            while not self._halt.wait(interval):
                try:
                    self.tick()
                except Exception:  # noqa: BLE001
                    log.exception("reminder tick failed")
        self._thread = threading.Thread(target=run, daemon=True, name="reminders")
        self._thread.start()

    def stop(self) -> None:
        self._halt.set()
