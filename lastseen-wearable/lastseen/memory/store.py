"""SQLite memory store. The vision tracker is the only writer."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

from lastseen.bus import Bus
from lastseen.types import TrackerEvent

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
  id TEXT PRIMARY KEY,           -- "inhaler"
  display_name TEXT,
  critical INTEGER DEFAULT 0,
  state TEXT,                    -- PLACED | HELD | HIDDEN | CARRIED_OUT | UNKNOWN
  zone TEXT,                     -- "nightstand", "bed", ...
  bbox TEXT,                     -- JSON [x1,y1,x2,y2] at last sighting
  confidence REAL,
  last_seen_ts REAL,
  last_event_id INTEGER
);

CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts REAL,
  item_id TEXT,
  kind TEXT,                     -- PICKED_UP | PLACED | HIDDEN | CARRIED_OUT | SEEN
  from_zone TEXT,
  to_zone TEXT,
  bbox TEXT,
  confidence REAL,
  snapshot_path TEXT,            -- annotated jpg
  clip_path TEXT                 -- 3 s mp4
);

CREATE TABLE IF NOT EXISTS asks (              -- every question + answer, for evals and the dashboard
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts REAL, source TEXT,          -- voice | photon | dashboard | eval
  question TEXT, item_id TEXT, answer TEXT, state TEXT, zone TEXT, latency_ms INTEGER
);
"""


def _url(path: str | None) -> str | None:
    return "/clips/" + Path(path).name if path else None


class Store:
    def __init__(self, path: str, bus: Bus, uncertain_conf: float = 0.6) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._bus = bus
        self._uc = uncertain_conf
        self._lock = threading.Lock()
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        with self._lock:
            self._db.executescript(SCHEMA)
            self._db.commit()

    def _unc(self, conf) -> bool:
        return conf is not None and conf < self._uc

    def _item(self, r: sqlite3.Row) -> dict:
        return {
            "id": r["id"], "display_name": r["display_name"],
            "critical": bool(r["critical"]), "state": r["state"], "zone": r["zone"],
            "bbox": json.loads(r["bbox"]) if r["bbox"] else None,
            "confidence": r["confidence"], "last_seen_ts": r["last_seen_ts"],
            "last_event_id": r["last_event_id"], "uncertain": self._unc(r["confidence"]),
        }

    def _event(self, r: sqlite3.Row) -> dict:
        return {
            "id": r["id"], "ts": r["ts"], "item_id": r["item_id"], "kind": r["kind"],
            "from_zone": r["from_zone"], "to_zone": r["to_zone"],
            "bbox": json.loads(r["bbox"]) if r["bbox"] else None,
            "confidence": r["confidence"], "uncertain": self._unc(r["confidence"]),
            "snapshot_path": r["snapshot_path"], "clip_path": r["clip_path"],
            "snapshot_url": _url(r["snapshot_path"]), "clip_url": _url(r["clip_path"]),
        }

    def upsert_item(self, id, display_name, critical, state, zone, bbox, confidence,
                    last_seen_ts, last_event_id=None) -> None:
        bb = json.dumps(list(bbox)) if bbox is not None else None
        with self._lock:
            self._db.execute(
                "INSERT INTO items (id, display_name, critical, state, zone, bbox, confidence,"
                " last_seen_ts, last_event_id) VALUES (?,?,?,?,?,?,?,?,?)"
                " ON CONFLICT(id) DO UPDATE SET display_name=excluded.display_name,"
                " critical=excluded.critical, state=excluded.state, zone=excluded.zone,"
                " bbox=excluded.bbox, confidence=excluded.confidence,"
                " last_seen_ts=excluded.last_seen_ts, last_event_id=excluded.last_event_id",
                (id, display_name, int(bool(critical)), state, zone, bb, confidence,
                 last_seen_ts, last_event_id))
            self._db.commit()
        self._bus.publish("item_update", item={
            "id": id, "display_name": display_name, "state": state, "zone": zone,
            "bbox": list(bbox) if bbox is not None else None, "confidence": confidence,
            "last_seen_ts": last_seen_ts, "uncertain": self._unc(confidence),
            "critical": bool(critical)})

    def add_event(self, ev: TrackerEvent, snapshot_path=None, clip_path=None) -> int:
        bb = json.dumps(list(ev.bbox)) if ev.bbox is not None else None
        with self._lock:
            cur = self._db.execute(
                "INSERT INTO events (ts, item_id, kind, from_zone, to_zone, bbox, confidence,"
                " snapshot_path, clip_path) VALUES (?,?,?,?,?,?,?,?,?)",
                (ev.ts, ev.item_id, ev.kind, ev.from_zone, ev.to_zone, bb, ev.confidence,
                 snapshot_path, clip_path))
            self._db.commit()
            eid = cur.lastrowid
        self._bus.publish("event", event={
            "id": eid, "item_id": ev.item_id, "kind": ev.kind, "from_zone": ev.from_zone,
            "to_zone": ev.to_zone, "bbox": list(ev.bbox) if ev.bbox is not None else None,
            "confidence": ev.confidence, "uncertain": self._unc(ev.confidence),
            "snapshot_url": _url(snapshot_path), "clip_url": _url(clip_path), "ts": ev.ts})
        return eid

    def get_item(self, id) -> dict | None:
        with self._lock:
            r = self._db.execute("SELECT * FROM items WHERE id=?", (id,)).fetchone()
        return self._item(r) if r else None

    def list_items(self) -> list[dict]:
        with self._lock:
            rows = self._db.execute("SELECT * FROM items ORDER BY id").fetchall()
        return [self._item(r) for r in rows]

    def recent_events(self, n=20, item_id=None) -> list[dict]:
        q, args = "SELECT * FROM events", []
        if item_id is not None:
            q += " WHERE item_id=?"
            args.append(item_id)
        q += " ORDER BY id DESC LIMIT ?"
        args.append(n)
        with self._lock:
            rows = self._db.execute(q, args).fetchall()
        return [self._event(r) for r in rows]

    def last_event(self, item_id, kinds) -> dict | None:
        kinds = tuple(kinds)
        if not kinds:
            return None
        marks = ",".join("?" * len(kinds))
        with self._lock:
            r = self._db.execute(
                f"SELECT * FROM events WHERE item_id=? AND kind IN ({marks})"
                " ORDER BY id DESC LIMIT 1", (item_id, *kinds)).fetchone()
        return self._event(r) if r else None

    def add_ask(self, source, question, item_id, answer, state, zone, latency_ms) -> int:

        with self._lock:
            cur = self._db.execute(
                "INSERT INTO asks (ts, source, question, item_id, answer, state, zone, latency_ms)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (time.time(), source, question, item_id, answer, state, zone, latency_ms))
            self._db.commit()
            return cur.lastrowid

    def recent_asks(self, n=20) -> list[dict]:
        with self._lock:
            rows = self._db.execute("SELECT * FROM asks ORDER BY id DESC LIMIT ?", (n,)).fetchall()
        return [dict(r) for r in rows]

    def reset_states(self) -> None:
        with self._lock:
            self._db.execute("DELETE FROM events")
            self._db.execute("DELETE FROM asks")
            self._db.execute("UPDATE items SET state='UNKNOWN', zone=NULL, bbox=NULL,"
                             " confidence=NULL, last_seen_ts=NULL, last_event_id=NULL")
            self._db.commit()
