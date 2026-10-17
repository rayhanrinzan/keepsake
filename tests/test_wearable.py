"""Issue #4/#5: wearable observation events and hand-object evidence. Synthetic sequences only."""
import json
from datetime import timedelta

import pytest

import events as E
from conftest import BED, DESK, STEP, T0, Clock, obs
from database import Database
from memory import SpatialMemory
from wearable import Hand, InteractionDetector, WearableObserver


class Feed:
    """Drives an observer/detector at ~5 fps and collects its events."""

    def __init__(self, target, start=T0):
        self.target, self.t, self.frame, self.events = target, start, 0, []

    def run(self, n, *observations, hands=None, cam=0.0, frame_id=None):
        for _ in range(n):
            self.frame += 1
            fid = frame_id if frame_id is not None else self.frame
            if isinstance(self.target, InteractionDetector):
                out = self.target.update(list(observations), list(hands or []), self.t, fid, cam)
            else:
                out = self.target.update(list(observations), self.t, fid, cam)
            self.events += out
            self.t += STEP
        return self.events

    def wait(self, seconds):
        self.t += timedelta(seconds=seconds)

    def types(self):
        return [e["event_type"] for e in self.events]


def hand_at(x, y, size=0.08):
    return Hand((x - size / 2, y - size / 2, x + size / 2, y + size / 2))


KEYS = "car key"
SPOT = (0.4, 0.6)
NEW_SPOT = (0.7, 0.6)


# ------------------------------------------------------------------ contract

def test_contract_fields_and_validation():
    ev = E.make_event(E.OBJECT_OBSERVED, object_id="car_key_01", category=KEYS, name="Keys",
                      timestamp=T0, confidence=0.8, bbox=(0.1, 0.1, 0.2, 0.2),
                      evidence=["stable_object_detection"], view_id="view-x", frame_id=3)
    assert set(E.FIELDS) <= set(ev) and ev["event_id"].startswith("obs-")
    assert ev["timestamp"].startswith("2026-10-15T14:30:00") and json.loads(json.dumps(ev)) == ev
    bad = dict(ev, event_type=E.PLACEMENT_CONFIRMED)  # placement without a prior pickup
    with pytest.raises(ValueError):
        E.validate_event(bad)
    with pytest.raises(ValueError):
        E.validate_event(dict(ev, evidence=["it looked moved"]))
    with pytest.raises(ValueError):
        E.validate_event(dict(ev, confidence=1.4))
    assert E.contract()["event_types"] == list(E.EVENT_TYPES)


# ------------------------------------------------------------------ issue #4: object_observed

def test_stable_detection_emits_one_object_observed():
    f = Feed(WearableObserver())
    f.run(20, obs(KEYS, SPOT, conf=0.6))
    assert f.types() == [E.OBJECT_OBSERVED]
    ev = f.events[0]
    E.validate_event(ev)
    assert ev["object_id"] == "car_key_01" and ev["name"] == "Keys" and ev["camera_mode"] == "wearable"
    assert ev["evidence"] == ["stable_object_detection", "camera_steady"]
    assert "from_region" not in ev and "to_region" not in ev  # no movement claim


def test_flicker_and_jumping_false_hits_are_ignored():
    f = Feed(WearableObserver())
    for _ in range(6):  # seen 1 frame in 3
        f.run(1, obs(KEYS, SPOT))
        f.run(2)
    assert f.events == []
    for x in (0.1, 0.5, 0.9, 0.1, 0.5, 0.9):  # every frame, but in a different place each time
        f.run(1, obs(KEYS, (x, 0.5)))
    assert f.events == []


def test_low_confidence_is_ignored():
    f = Feed(WearableObserver())
    f.run(10, obs("wallet", SPOT, conf=0.4))  # wallet needs 0.6
    assert f.events == []


def test_brief_occlusion_and_tracker_id_swaps_do_not_duplicate():
    f = Feed(WearableObserver())
    f.run(5, obs(KEYS, SPOT, tid=1))
    f.run(4)  # covered for 0.8 s
    f.run(5, obs(KEYS, SPOT, tid=7))  # tracker gave it a new id
    f.run(5, obs(KEYS, SPOT, tid=None))
    assert f.types() == [E.OBJECT_OBSERVED]


def test_duplicate_and_out_of_order_frames_are_dropped():
    obsr = WearableObserver(min_hits=3)
    out = []
    for _ in range(5):  # the same frame delivered five times
        out += obsr.update([obs(KEYS, SPOT)], T0, frame_id=1)
    assert out == []
    out += obsr.update([obs(KEYS, SPOT)], T0 - STEP, frame_id=2)  # older timestamp
    assert out == []


def test_camera_motion_frames_add_no_evidence():
    f = Feed(WearableObserver())
    f.run(10, obs(KEYS, SPOT), cam=0.6)  # blurry pan
    assert f.events == []
    f.run(3, obs(KEYS, SPOT))
    assert f.types() == [E.OBJECT_OBSERVED]


def test_resighting_after_absence_respects_cooldown():
    f = Feed(WearableObserver(cooldown_seconds=30))
    f.run(5, obs(KEYS, SPOT))
    f.run(15)  # gone 3 s: no longer present
    f.run(5, obs(KEYS, NEW_SPOT))  # back within 30 s: no duplicate event
    assert f.types() == [E.OBJECT_OBSERVED]
    f.run(15)
    f.wait(40)
    f.run(5, obs(KEYS, NEW_SPOT))
    assert f.types() == [E.OBJECT_OBSERVED, E.OBJECT_OBSERVED]


def test_wearable_memory_never_claims_movement(tmp_path, regions):
    db = Database(tmp_path / "w.db")
    mem = SpatialMemory(db, regions, camera_mode="wearable")
    clock = Clock(mem)
    clock.frames(6, obs("bottle", DESK))
    clock.frames(6, obs("bottle", BED))  # same bottle, the wearer turned around
    assert [e["event_type"] for e in clock.events] == ["first_seen", "reconfirmed"]
    assert [e["event_type"] for e in db.get_events()] == ["first_seen"]
    assert db.get_by_category("bottle")["region"] == "Bed"  # last seen there, not "moved there"
    db.close()


def test_observations_round_trip_through_the_database(db):
    f = Feed(WearableObserver())
    f.run(5, obs(KEYS, SPOT))
    f.run(15)
    f.wait(40)
    f.run(5, obs("airpods case", NEW_SPOT, conf=0.5))
    for ev in f.events:
        db.add_observation(ev)
    db.set_observation_snapshot(f.events[0]["event_id"], 12)
    got = db.get_observations()
    assert [g["object_id"] for g in got] == ["airpods_case_01", "car_key_01"]  # newest first
    assert got[1]["snapshot_id"] == 12 and got[0]["seq"] > got[1]["seq"]
    assert db.get_observations(after_seq=got[1]["seq"]) == [got[0]]
    assert db.get_observations(object_id="car_key_01")[0]["event_id"] == f.events[0]["event_id"]
    db.clear()
    assert db.get_observations() == []


# ------------------------------------------------------------------ issue #5: hand evidence

def test_hand_passing_by_without_touching_is_nothing():
    f = Feed(InteractionDetector())
    f.run(5, obs(KEYS, SPOT))
    for x in (0.0, 0.1, 0.9, 1.0):  # hand moves across the frame far from the keys
        f.run(1, obs(KEYS, SPOT), hands=[hand_at(x, 0.2)])
    f.run(1, obs(KEYS, SPOT), hands=[hand_at(*SPOT)])  # one-frame brush
    f.run(5, obs(KEYS, SPOT))
    assert f.events == []


def test_hand_covering_the_object_is_not_a_pickup():
    f = Feed(InteractionDetector())
    f.run(5, obs(KEYS, SPOT))
    f.run(3, obs(KEYS, SPOT), hands=[hand_at(*SPOT)])  # touching
    f.run(5, hands=[hand_at(*SPOT, size=0.2)])  # hand covers it: keys not detected
    f.run(1, obs(KEYS, SPOT))  # hand leaves, keys are still there
    f.run(10, obs(KEYS, SPOT))
    assert f.types() == [E.INTERACTION_CANDIDATE]  # proximity only, honestly reported
    assert f.events[0]["evidence"] == ["hand_near_object", "camera_steady"]


def test_camera_pan_is_not_manipulation():
    f = Feed(InteractionDetector())
    f.run(5, obs(KEYS, SPOT))
    for x in (0.45, 0.55, 0.65, 0.75):  # everything shifts while the camera turns
        f.run(1, obs(KEYS, (x, 0.6)), hands=[hand_at(x, 0.6)], cam=0.5)
    f.run(10, obs(KEYS, NEW_SPOT))
    assert f.events == []


def test_pickup_then_put_down_sequence():
    f = Feed(InteractionDetector())
    f.run(5, obs(KEYS, SPOT))  # resting
    f.run(2, obs(KEYS, SPOT), hands=[hand_at(*SPOT)])  # hand on keys
    for x in (0.48, 0.56):  # keys move with the hand
        f.run(1, obs(KEYS, (x, 0.6)), hands=[hand_at(x, 0.6)])
    f.run(8, hands=[hand_at(0.9, 0.9)])  # carried out of view
    f.run(2, obs(KEYS, NEW_SPOT), hands=[hand_at(*NEW_SPOT)])  # being set down
    f.run(6, obs(KEYS, NEW_SPOT))  # let go, sitting still
    assert f.types() == [E.INTERACTION_CANDIDATE, E.POSSIBLE_PICKUP, E.PLACEMENT_CONFIRMED]
    pick, place = f.events[1], f.events[2]
    assert "object_moved_with_hand" in pick["evidence"]
    assert place["evidence"][0] == "prior_possible_pickup" and "hand_released" in place["evidence"]
    assert abs((place["bbox"][0] + place["bbox"][2]) / 2 - NEW_SPOT[0]) < 0.01
    assert place["confidence"] > pick["confidence"] > f.events[0]["confidence"]
    for e in f.events:
        E.validate_event(e)


def test_object_leaving_with_the_hand_is_a_possible_pickup():
    f = Feed(InteractionDetector())
    f.run(5, obs(KEYS, SPOT))
    f.run(2, obs(KEYS, SPOT), hands=[hand_at(*SPOT)])
    f.run(2, hands=[hand_at(*SPOT)])  # hand over the spot, keys gone
    f.run(4, hands=[hand_at(0.1, 0.1)])  # hand moved away, keys still gone
    assert f.types() == [E.INTERACTION_CANDIDATE, E.POSSIBLE_PICKUP]
    assert "object_left_with_hand" in f.events[1]["evidence"] and f.events[1]["confidence"] < 0.7


def test_placement_needs_a_steady_camera_and_expires():
    f = Feed(InteractionDetector(hold_seconds=60))
    f.run(5, obs(KEYS, SPOT))
    f.run(2, obs(KEYS, SPOT), hands=[hand_at(*SPOT)])
    f.run(2, hands=[hand_at(*SPOT)])
    f.run(4, hands=[hand_at(0.1, 0.1)])
    f.run(10, obs(KEYS, NEW_SPOT), cam=0.5)  # walking around with it visible: not a placement
    assert E.PLACEMENT_CONFIRMED not in f.types()
    f.wait(90)  # never set down while watched: give up
    f.run(10, obs(KEYS, NEW_SPOT))
    assert E.PLACEMENT_CONFIRMED not in f.types()


def test_observations_api(tmp_path, monkeypatch):
    import importlib

    from fastapi.testclient import TestClient
    from conftest import TEST_AREAS
    from spatial import save_regions
    save_regions(TEST_AREAS, tmp_path / "regions.json")
    for k, v in {"CAMERA_ENABLED": "0", "DB_PATH": str(tmp_path / "api.db"),
                 "SNAPSHOT_DIR": str(tmp_path / "snaps"), "REGIONS": str(tmp_path / "regions.json")}.items():
        monkeypatch.setenv(f"CTRLF_{k}", v)
    import main
    main = importlib.reload(main)
    with TestClient(main.app) as c:
        f = Feed(WearableObserver())
        f.run(5, obs(KEYS, SPOT))
        main.db.add_observation(f.events[0])
        got = c.get("/api/observations").json()
        assert [g["event_id"] for g in got] == [f.events[0]["event_id"]]
        assert c.get("/api/observations", params={"object_id": "keys"}).json() == got  # alias works
        assert c.get("/api/observations", params={"after_seq": got[0]["seq"]}).json() == []
        assert c.get("/api/observations", params={"event_type": "moved"}).status_code == 422
        assert c.get("/api/observations/contract").json()["version"] == E.CONTRACT_VERSION
        assert c.get("/api/health").json()["camera_mode"] == "wearable"
        c.delete("/api/memory")
        assert c.get("/api/observations").json() == []


def test_camera_motion_ignores_the_moving_hand():
    import numpy as np
    from vision import MotionDetector
    m = MotionDetector()
    a = np.zeros((90, 160, 3), np.uint8)
    b = a.copy()
    b[30:60, 60:100] = 255  # only the hand region changes
    m.update(a)
    m.update(b)
    assert m.background([]) > 0.05
    assert m.background([(0.35, 0.3, 0.65, 0.7)]) == 0.0
