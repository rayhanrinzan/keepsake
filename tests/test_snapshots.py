"""Snapshot capture, dedupe, retention, persistence and deletion (synthetic frames)."""
from conftest import DESK, Pipeline, obs
from database import Database
from snapshots import SnapshotStore


def photo(oid="bottle_01", t="2026-10-15T14:30:00+00:00", bbox=(0.1, 0.1, 0.2, 0.2),
          event_type="object_observed"):
    """What vision.py hands SnapshotStore for an observation event."""
    return {"object_id": oid, "event_type": event_type, "timestamp": t, "region": None,
            "bbox": bbox, "confidence": 0.9}


def test_observation_photo_is_written_and_linked(mem, store, db):
    events = Pipeline(mem, store).frames(6, obs(pos=DESK))
    assert [e["event_type"] for e in events] == ["object_observed"]
    [s] = db.get_snapshots("bottle_01")
    assert s["event_type"] == "object_observed" and s["region"] is None
    assert s["x0"] < DESK[0] < s["x1"]
    assert store.path_for(s["filename"]).stat().st_size > 0
    assert db.get_observations(limit=1)[0]["snapshot_id"] == s["id"]  # event points at its photo


def test_people_walking_by_add_no_photos(mem, store, db):
    p = Pipeline(mem, store)
    p.frames(6, obs(pos=DESK))
    p.frames(25, obs(pos=DESK), obs(cat="person", pos=(0.8, 0.5), size=0.5))
    assert len(db.get_snapshots("bottle_01")) == 1  # one per item per cooldown


def test_duplicate_snapshots_suppressed(store, db, frame):
    assert store.submit(photo(), frame)
    assert not store.submit(photo(), frame)  # same spot within cooldown
    store.flush()
    assert len(db.get_snapshots("bottle_01")) == 1


def test_capture_disabled_keeps_memory(mem, store, db):
    store.enabled = False
    Pipeline(mem, store).frames(6, obs())
    assert db.get_snapshots("bottle_01") == []
    assert db.get_by_category("bottle")["visible"]  # memory still updates


def test_missing_frame_skips_photo(store, db):
    assert store.submit(photo(), None) is False
    store.flush()
    assert db.get_snapshots("bottle_01") == []


def test_retention_limit_deletes_old_files(store, db, frame):
    store.cooldown = 0
    for i in range(6):
        store.submit(photo("backpack_01", f"2026-10-15T14:3{i}:00+00:00", (0.1 * i, 0.1, 0.1 * i + 0.05, 0.2)),
                     frame)
    store.flush()
    assert len(db.get_snapshots("backpack_01")) == 3
    assert len(list(store.dir.glob("*.jpg"))) == 3


def test_photos_persist_across_restart(tmp_path, store, db, frame):
    store.submit(photo(), frame)
    store.flush()
    name = db.get_snapshots("bottle_01")[0]["filename"]
    db2 = Database(tmp_path / "t.db")
    store2 = SnapshotStore(db2, tmp_path / "snaps")
    assert db2.get_snapshots("bottle_01")[0]["filename"] == name and store2.path_for(name)


def test_clear_deletes_photos_and_rejects_bad_paths(mem, store, db, frame):
    store.submit(photo(), frame)
    store.flush()
    (store.dir / "notes.txt").write_text("keep me")
    mem.reset()
    store.clear()
    assert db.get_snapshots("bottle_01") == [] and list(store.dir.glob("*.jpg")) == []
    assert (store.dir / "notes.txt").exists()
    assert store.path_for("../t.db") is None and store.path_for("notes.txt") is None
