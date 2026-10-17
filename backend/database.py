"""SQLite persistence for object memories, movement events, snapshot metadata and settings.

Snapshot *images* live on disk (see snapshots.py); SQLite stores only their metadata.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS objects (
    object_id  TEXT PRIMARY KEY,
    category   TEXT NOT NULL UNIQUE,
    name       TEXT NOT NULL,
    region     TEXT,
    x          REAL,
    y          REAL,
    last_seen  TEXT NOT NULL,
    visible    INTEGER NOT NULL DEFAULT 0,
    confidence REAL,
    track_id   INTEGER
);
CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    object_id   TEXT NOT NULL,
    name        TEXT NOT NULL,
    from_region TEXT,
    to_region   TEXT NOT NULL,
    timestamp   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS snapshots (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    object_id   TEXT NOT NULL,
    event_type  TEXT NOT NULL,
    timestamp   TEXT NOT NULL,
    region      TEXT,
    x0 REAL, y0 REAL, x1 REAL, y1 REAL,
    confidence  REAL,
    filename    TEXT NOT NULL UNIQUE,
    view_id     TEXT
);
CREATE INDEX IF NOT EXISTS snapshots_object ON snapshots (object_id, id);
CREATE TABLE IF NOT EXISTS observations (
    seq         INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id    TEXT NOT NULL UNIQUE,
    event_type  TEXT NOT NULL,
    object_id   TEXT NOT NULL,
    timestamp   TEXT NOT NULL,
    snapshot_id INTEGER,
    payload     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS observations_object ON observations (object_id, seq);
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

# Columns added after the first release; applied to existing databases on open.
MIGRATIONS = {
    "objects": {"view_id": "TEXT", "lost_while_moving": "INTEGER NOT NULL DEFAULT 0"},
    "events": {"event_type": "TEXT NOT NULL DEFAULT 'moved'", "view_id": "TEXT"},
}

OBJECT_FIELDS = ("object_id", "category", "name", "region", "x", "y", "last_seen", "visible",
                 "confidence", "track_id", "view_id", "lost_while_moving")
SNAPSHOT_FIELDS = ("object_id", "event_type", "timestamp", "region", "x0", "y0", "x1", "y1",
                   "confidence", "filename", "view_id")


def _obj(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    d = dict(row)
    d["visible"] = bool(d["visible"])
    d["lost_while_moving"] = bool(d.get("lost_while_moving"))
    return d


class Database:
    def __init__(self, path: str | Path):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._migrate()
        self._conn.commit()

    def _migrate(self) -> None:
        for table, cols in MIGRATIONS.items():
            have = {r["name"] for r in self._conn.execute(f"PRAGMA table_info({table})")}
            for col, decl in cols.items():
                if col not in have:
                    self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")

    # ---- objects ----
    def upsert_object(self, obj: dict) -> None:
        cols = ", ".join(OBJECT_FIELDS)
        marks = ", ".join("?" for _ in OBJECT_FIELDS)
        updates = ", ".join(f"{f}=excluded.{f}" for f in OBJECT_FIELDS if f != "object_id")
        values = [int(bool(obj.get(f))) if f in ("visible", "lost_while_moving") else obj.get(f)
                  for f in OBJECT_FIELDS]
        with self._lock:
            self._conn.execute(
                f"INSERT INTO objects ({cols}) VALUES ({marks}) "
                f"ON CONFLICT(object_id) DO UPDATE SET {updates}", values)
            self._conn.commit()

    def get_objects(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM objects ORDER BY name").fetchall()
        return [_obj(r) for r in rows]

    def get_object(self, object_id: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM objects WHERE object_id = ?", (object_id,)).fetchone()
        return _obj(row)

    def get_by_category(self, category: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM objects WHERE category = ?", (category,)).fetchone()
        return _obj(row)

    # ---- events ----
    def add_event(self, object_id: str, name: str, from_region: str | None, to_region: str,
                  timestamp: str, event_type: str = "moved", view_id: str | None = None) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO events (object_id, name, from_region, to_region, timestamp, "
                "event_type, view_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (object_id, name, from_region, to_region, timestamp, event_type, view_id))
            self._conn.commit()

    def get_events(self, limit: int = 50) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    # ---- snapshots ----
    def add_snapshot(self, snap: dict) -> int:
        cols = ", ".join(SNAPSHOT_FIELDS)
        marks = ", ".join("?" for _ in SNAPSHOT_FIELDS)
        with self._lock:
            cur = self._conn.execute(f"INSERT INTO snapshots ({cols}) VALUES ({marks})",
                                     [snap.get(f) for f in SNAPSHOT_FIELDS])
            self._conn.commit()
            return int(cur.lastrowid)

    def get_snapshot(self, snapshot_id: int) -> dict | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM snapshots WHERE id = ?",
                                     (snapshot_id,)).fetchone()
        return dict(row) if row else None

    def get_snapshots(self, object_id: str, limit: int = 50) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM snapshots WHERE object_id = ? ORDER BY id DESC LIMIT ?",
                (object_id, limit)).fetchall()
        return [dict(r) for r in rows]

    def latest_snapshots(self) -> dict[str, dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT s.* FROM snapshots s JOIN (SELECT object_id, MAX(id) AS id FROM snapshots "
                "GROUP BY object_id) m ON s.id = m.id").fetchall()
        return {r["object_id"]: dict(r) for r in rows}

    def prune_snapshots(self, object_id: str, keep: int) -> list[str]:
        """Delete all but the newest `keep` snapshot rows for an object; return their filenames."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, filename FROM snapshots WHERE object_id = ? ORDER BY id DESC "
                "LIMIT -1 OFFSET ?", (object_id, keep)).fetchall()
            self._conn.executemany("DELETE FROM snapshots WHERE id = ?", [(r["id"],) for r in rows])
            self._conn.commit()
        return [r["filename"] for r in rows]

    def all_snapshot_files(self) -> list[str]:
        with self._lock:
            return [r["filename"] for r in self._conn.execute("SELECT filename FROM snapshots")]

    # ---- wearable observation events (contract in events.py) ----
    def add_observation(self, event: dict) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO observations (event_id, event_type, object_id, timestamp, snapshot_id, "
                "payload) VALUES (?, ?, ?, ?, ?, ?)",
                (event["event_id"], event["event_type"], event["object_id"], event["timestamp"],
                 event.get("snapshot_id"), json.dumps(event)))
            self._conn.commit()
            return int(cur.lastrowid)

    def set_observation_snapshot(self, event_id: str, snapshot_id: int) -> None:
        with self._lock:
            self._conn.execute("UPDATE observations SET snapshot_id = ? WHERE event_id = ?",
                               (snapshot_id, event_id))
            self._conn.commit()

    def get_observations(self, limit: int = 50, after_seq: int = 0, event_type: str | None = None,
                         object_id: str | None = None) -> list[dict]:
        """Newest first. `seq` is a cursor: pass the largest seq you have as after_seq to poll."""
        sql, args = "SELECT * FROM observations WHERE seq > ?", [after_seq]
        if event_type:
            sql, args = sql + " AND event_type = ?", args + [event_type]
        if object_id:
            sql, args = sql + " AND object_id = ?", args + [object_id]
        with self._lock:
            rows = self._conn.execute(sql + " ORDER BY seq DESC LIMIT ?", args + [limit]).fetchall()
        out = []
        for r in rows:
            ev = json.loads(r["payload"])
            ev.update(seq=r["seq"], snapshot_id=r["snapshot_id"])
            out.append(ev)
        return out

    # ---- settings ----
    def get_setting(self, key: str, default: str | None = None) -> str | None:
        with self._lock:
            row = self._conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self._lock:
            self._conn.execute("INSERT INTO settings (key, value) VALUES (?, ?) "
                               "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
            self._conn.commit()

    # ---- lifecycle ----
    def clear(self) -> None:
        """Forget objects, events, observations and snapshot rows (settings such as the camera view are kept)."""
        with self._lock:
            for table in ("objects", "events", "snapshots", "observations"):
                self._conn.execute(f"DELETE FROM {table}")
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()
