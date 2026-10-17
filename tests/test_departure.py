"""Departure feed for Departure Alerts: PresenceTracker "left" events become possible departures."""
import importlib
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from conftest import TEST_AREAS, obs
from departure import DepartureFeed, DeparturePresence, TargetTracker, hold_reason
from spatial import save_regions


def person(tid, pos, size=0.3, conf=0.8):
    return obs("person", pos=pos, conf=conf, tid=tid, size=size)


def run(tracker, frames, *people, t=0.0, step=0.2):
    out = []
    for _ in range(frames):
        ev = tracker.update(list(people), now=t)
        if ev:
            out.append(ev)
        t += step
    return out, t


ME, OTHER, THIRD = (0.5, 0.5), (0.2, 0.5), (0.8, 0.5)


def test_locks_onto_the_closest_person_in_a_crowd():
    tr = TargetTracker()
    evs, _ = run(tr, 3, person(1, ME, size=0.4), person(2, OTHER, size=0.2), person(3, THIRD, size=0.2))
    assert evs == ["acquired"] and tr.target_id == 1 and tr.people == 3


def test_target_leaving_while_others_stay_is_a_departure():
    tr = TargetTracker()
    _, t = run(tr, 5, person(1, ME, size=0.4), person(2, OTHER), person(3, THIRD))
    evs, t = run(tr, 20, person(2, OTHER), person(3, THIRD), t=t)  # 4 s, the crowd stays
    assert evs == ["left", "acquired"] and tr.left_count == 1  # then follows the next person
    assert tr.target_id in (2, 3)


def test_others_leaving_is_not_a_departure():
    tr = TargetTracker()
    _, t = run(tr, 5, person(1, ME, size=0.4), person(2, OTHER), person(3, THIRD))
    evs, _ = run(tr, 20, person(1, ME, size=0.4), t=t)
    assert evs == [] and tr.target_id == 1


def test_keeps_the_target_when_someone_closer_walks_in():
    tr = TargetTracker()
    _, t = run(tr, 5, person(1, ME, size=0.3))
    evs, _ = run(tr, 10, person(1, ME, size=0.3), person(9, OTHER, size=0.6), t=t)
    assert evs == [] and tr.target_id == 1


def test_new_track_id_at_the_same_spot_is_still_the_target():
    tr = TargetTracker()
    _, t = run(tr, 5, person(1, ME, size=0.4), person(2, OTHER))
    _, t = run(tr, 3, person(2, OTHER), t=t)  # occluded for 0.6 s
    evs, t = run(tr, 20, person(7, (0.52, 0.5), size=0.4), person(2, OTHER), t=t)  # new id, same place
    assert evs == [] and tr.target_id == 7


def test_a_bystander_is_never_mistaken_for_the_target():
    tr = TargetTracker()
    near = (0.55, 0.5)  # standing right next to the target
    _, t = run(tr, 5, person(1, ME, size=0.4), person(2, near))
    evs, _ = run(tr, 20, person(2, near), t=t)
    assert evs[0] == "left" and tr.left_count == 1


def test_brief_dropout_of_the_target_is_not_a_departure():
    tr = TargetTracker()
    _, t = run(tr, 5, person(1, ME))
    evs, t = run(tr, 10, t=t)  # 2 s unseen, under leave_seconds
    evs2, _ = run(tr, 5, person(1, ME), t=t)
    assert evs == [] and evs2 == [] and tr.left_count == 0


def test_one_frame_false_positive_is_never_a_target():
    tr = TargetTracker()
    evs, t = run(tr, 1, person(1, ME))
    evs2, _ = run(tr, 20, t=t)
    assert evs == [] and evs2 == [] and tr.target_id is None


def test_low_confidence_or_untracked_people_are_ignored():
    tr = TargetTracker()
    untracked = obs("person", pos=ME, conf=0.8, tid=None, size=0.3)
    evs, _ = run(tr, 10, person(1, ME, conf=0.2), untracked)
    assert evs == [] and tr.people == 0


def test_departure_presence_keeps_the_original_presence_behaviour():
    p = DeparturePresence()
    t = 0.0
    out = []
    for i in range(30):
        seen = [person(1, ME)] if i < 10 else []
        out.append(p.update(seen, now=t))
        t += 0.2
    assert [e for e in out if e] == ["entered", "left"]  # PresenceTracker's own events
    st = p.status()
    assert st["target_left_count"] == 1 and st["target_left_count"] == 1
    p.update([person(1, ME)] * 1, now=t)
    p.reset()
    assert p.status()["target_tracking"] is False


def test_tracked_departure_becomes_one_feed_event():
    p, f = DeparturePresence(), DepartureFeed()
    f.sync(p.status(), None, "view-a")  # baseline
    t = 0.0
    evs = []
    for i in range(30):
        p.update([person(1, ME), person(2, OTHER, size=0.2)] if i < 10 else [person(2, OTHER, size=0.2)], now=t)
        ev = f.sync(p.status(), None, "view-a")
        if ev:
            evs.append(ev)
        t += 0.2
    assert len(evs) == 1 and evs[0]["source"] == "tracked_person" and evs[0]["view_id"] == "view-a"


def test_departures_from_before_the_first_poll_are_ignored():
    f = DepartureFeed()
    assert f.sync({"target_left_count": 4, "target_left_at": 1.0}, None, "v") is None
    assert f.sync({"target_left_count": 5, "target_left_at": 2.0}, None, "v")["id"] == 1


@pytest.mark.parametrize("hold", ["camera_shift", "camera_dark", "camera_repositioning"])
def test_untrusted_view_suppresses_departures(hold):
    f = DepartureFeed()
    f.sync({"target_left_count": 0}, None, "v")
    assert f.sync({"target_left_count": 1, "target_left_at": 1.0}, hold, "v") is None
    assert f.events_after(0) == [] and f.status()["suppressed"] == 1
    assert f.status()["last_suppressed"] == hold


def test_no_presence_data_means_no_events():
    f = DepartureFeed()
    assert f.sync({"camera": "disabled"}, None, "v") is None
    assert f.latest_id() == 0


def test_manual_departures_get_their_own_ids():
    f = DepartureFeed()
    f.sync({"target_left_count": 0}, None, "v")
    a = f.simulate("v")
    b = f.sync({"target_left_count": 1, "target_left_at": 1.0}, None, "v")
    assert (a["source"], b["source"]) == ("manual", "tracked_person") and b["id"] == a["id"] + 1
    assert f.events_after(a["id"]) == [b]


def test_hold_reason_reads_modes_memory_and_camera():
    m = SimpleNamespace(mode="MONITORING", paused=False, _suspended_until=None)
    assert hold_reason(m, m, {"camera": "active"}) is None
    assert hold_reason(SimpleNamespace(mode="CALIBRATING"), m, {}) == "camera_repositioning"
    assert hold_reason(m, m, {"camera_shift_at": 100}, now=105) == "camera_shift"
    assert hold_reason(m, m, {"warning": "The camera is sending black frames. …"}) == "camera_dark"
    assert hold_reason(m, m, {"camera": "error"}) == "camera_unavailable"


@pytest.fixture
def api(tmp_path, monkeypatch):
    save_regions(TEST_AREAS, tmp_path / "regions.json")
    monkeypatch.setenv("CTRLF_CAMERA_ENABLED", "0")
    monkeypatch.setenv("CTRLF_DB_PATH", str(tmp_path / "api.db"))
    monkeypatch.setenv("CTRLF_SNAPSHOT_DIR", str(tmp_path / "snaps"))
    monkeypatch.setenv("CTRLF_REGIONS", str(tmp_path / "regions.json"))
    import main
    main = importlib.reload(main)
    with TestClient(main.app) as c:
        yield c, main


def test_departure_api(api):
    c, main = api
    assert c.get("/api/departures").json() == {"events": [], "latest_id": 0}
    assert c.post("/api/departures/simulate").status_code == 403
    ev = c.post("/api/departures/simulate", headers={"X-Keepsake-Local": "1"}).json()
    assert ev["source"] == "manual" and ev["view_id"] == main.memory.view_id
    assert c.get("/api/departures?after=0").json()["latest_id"] == ev["id"]
    assert c.get(f"/api/departures?after={ev['id']}").json()["events"] == []
    ctx = c.get("/api/departures/context").json()
    assert ctx["hold"] is None and ctx["mode"] == "MONITORING" and ctx["places"] == {}


def test_departure_api_follows_the_tracked_person(api):
    c, main = api
    main.worker = SimpleNamespace(status={"camera": "active", "target_left_count": 0,
                                          "target_left_at": None, "person_present": True})
    try:
        assert c.get("/api/departures").json()["events"] == []  # baseline
        main.worker.status.update(target_left_count=1, target_left_at=1792250000.0,
                                  person_present=False)
        evs = c.get("/api/departures").json()["events"]
        assert [e["source"] for e in evs] == ["tracked_person"] and evs[0]["at"].startswith("2026-10-17")
        main.worker.status.update(target_left_count=2, camera_shift_at=time.time())
        assert c.get("/api/departures?after=1").json()["events"] == []  # camera moved: suppressed
        c.post("/api/reposition/start")
        assert c.get("/api/departures/context").json()["hold"] == "camera_repositioning"
    finally:
        main.worker = None
