"""Departure feed for Departure Alerts: PresenceTracker "left" events become possible departures."""
import importlib
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from conftest import TEST_AREAS, obs
from departure import DepartureFeed, hold_reason
from presence import PresenceTracker
from spatial import save_regions


def walk(tracker, feed, frames, person, t, hold=None, step=0.2):
    """Feed frames through the real PresenceTracker and sync the feed after each, like polling."""
    out = []
    for _ in range(frames):
        tracker.update([obs("person", conf=0.8, size=0.4)] if person else [], now=t)
        ev = feed.sync(tracker.status(), hold, "view-a")
        if ev:
            out.append(ev)
        t += step
    return out, t


def test_someone_leaving_the_room_is_one_departure():
    p, f = PresenceTracker(), DepartureFeed()
    f.sync(p.status(), None, "view-a")  # baseline
    evs, t = walk(p, f, 10, True, 0.0)
    evs2, _ = walk(p, f, 15, False, t)  # 3 s gone
    assert evs == [] and len(evs2) == 1
    assert evs2[0]["source"] == "presence" and evs2[0]["view_id"] == "view-a"
    assert f.events_after(0) == evs2 and f.latest_id() == 1


def test_brief_dropout_is_not_a_departure():
    p, f = PresenceTracker(), DepartureFeed()
    f.sync(p.status(), None, "v")
    _, t = walk(p, f, 10, True, 0.0)
    evs, t = walk(p, f, 5, False, t)  # 1 s missed detections
    evs2, _ = walk(p, f, 10, True, t)
    assert evs == [] and evs2 == []


def test_departures_from_before_the_first_poll_are_ignored():
    f = DepartureFeed()
    assert f.sync({"person_left_count": 4, "person_left_at": 1.0}, None, "v") is None
    assert f.sync({"person_left_count": 5, "person_left_at": 2.0}, None, "v")["id"] == 1


@pytest.mark.parametrize("hold", ["camera_shift", "camera_dark", "camera_repositioning"])
def test_untrusted_view_suppresses_departures(hold):
    f = DepartureFeed()
    f.sync({"person_left_count": 0}, None, "v")
    assert f.sync({"person_left_count": 1, "person_left_at": 1.0}, hold, "v") is None
    assert f.events_after(0) == [] and f.status()["suppressed"] == 1
    assert f.status()["last_suppressed"] == hold


def test_no_presence_data_means_no_events():
    f = DepartureFeed()
    assert f.sync({"camera": "disabled"}, None, "v") is None
    assert f.latest_id() == 0


def test_manual_departures_get_their_own_ids():
    f = DepartureFeed()
    f.sync({"person_left_count": 0}, None, "v")
    a = f.simulate("v")
    b = f.sync({"person_left_count": 1, "person_left_at": 1.0}, None, "v")
    assert (a["source"], b["source"]) == ("manual", "presence") and b["id"] == a["id"] + 1
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


def test_departure_api_follows_the_worker_presence(api):
    c, main = api
    main.worker = SimpleNamespace(status={"camera": "active", "person_left_count": 0,
                                          "person_left_at": None, "person_present": True})
    try:
        assert c.get("/api/departures").json()["events"] == []  # baseline
        main.worker.status.update(person_left_count=1, person_left_at=1792250000.0,
                                  person_present=False)
        evs = c.get("/api/departures").json()["events"]
        assert [e["source"] for e in evs] == ["presence"] and evs[0]["at"].startswith("2026-10-17")
        main.worker.status.update(person_left_count=2, camera_shift_at=time.time())
        assert c.get("/api/departures?after=1").json()["events"] == []  # camera moved: suppressed
        c.post("/api/reposition/start")
        assert c.get("/api/departures/context").json()["hold"] == "camera_repositioning"
    finally:
        main.worker = None
