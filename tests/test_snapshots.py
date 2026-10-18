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


def test_thumbnail_keeps_up_with_last_seen_on_a_moving_camera(mem, store, db, monkeypatch):
    """Seen live: "last seen 5 seconds ago" with a photo from hours earlier, because the observer
    needs a still camera. Every memory sighting now refreshes the photo (at most every 8 s)."""
    from types import SimpleNamespace

    import numpy as np

    import vision
    from conftest import Clock
    clock = [1000.0]
    monkeypatch.setattr(vision.time, "monotonic", lambda: clock[0])
    worker = SimpleNamespace(memory=mem, snapshots=store, _photo_at={})
    c = Clock(mem)
    image = np.full((360, 640, 3), 90, np.uint8)
    taken = []
    for step in range(60):  # 12 s at 5 fps, the item jumping around the frame (camera moving)
        pos = (0.2 + 0.6 * (step % 3) / 2, 0.5)
        c.frames(1, obs("wallet", pos=pos))
        vision.VisionWorker._refresh_photos(worker, image)
        clock[0] += 0.2
    store.flush()
    taken = db.get_snapshots("wallet_01")
    assert len(taken) == 2 and {s["event_type"] for s in taken} == {"seen"}  # at ~0.4 s and ~8.4 s


def test_frozen_feed_means_identical_frames_not_a_still_scene():
    """A still phone on a table can measure zero motion; only repeated identical frames are frozen."""
    from types import SimpleNamespace

    import numpy as np

    import vision
    w = SimpleNamespace(_still_frames=0, _last_sample=None)
    rng = np.random.default_rng(0)
    still = np.full((360, 640, 3), 120, np.uint8)

    def feed(frame):
        sample = frame[::16, ::16]
        same = w._last_sample is not None and np.array_equal(sample, w._last_sample)
        w._last_sample = sample.copy()
        w._still_frames = w._still_frames + 1 if same else 0

    for _ in range(30):  # live sensor: tiny noise every frame, even on a still scene
        feed(np.clip(still.astype(int) + rng.integers(-2, 3, still.shape), 0, 255).astype(np.uint8))
    assert w._still_frames == 0
    for _ in range(30):  # paused feed: the same frame again and again
        feed(still)
    assert w._still_frames >= 25
    assert "np.array_equal(sample, self._last_sample)" in open(vision.__file__).read()


def test_highlighted_photo_circles_the_item_in_white(store, db):
    import cv2
    import numpy as np
    frame = np.full((360, 640, 3), 90, np.uint8)
    store.submit(photo(bbox=(0.4, 0.4, 0.5, 0.5)), frame)
    store.flush()
    [s] = db.get_snapshots("bottle_01")
    image = cv2.imdecode(np.frombuffer(store.highlighted(s), np.uint8), cv2.IMREAD_COLOR)
    b, g, r = (int(v) for v in image[int(0.45 * 360), int(0.45 * 640 + 0.075 * 640)])
    assert min(r, g, b) > 200  # white ring at the right edge of the padded box
    assert abs(int(image[10, 10][2]) - 90) < 10  # rest of the photo untouched
    raw = cv2.imread(str(store.path_for(s["filename"])))
    assert abs(int(raw[int(0.45 * 360), int(0.525 * 640)][2]) - 90) < 10  # stored photo stays clean
