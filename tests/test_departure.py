"""Exit-zone departure detection with synthetic person boxes (5 fps), plus its API."""
import importlib

import pytest
from fastapi.testclient import TestClient

from conftest import TEST_AREAS
from departure import IDLE, DepartureDetector, hold_reason, overlap
from spatial import save_regions

EXIT = (0.85, 0.0, 1.0, 1.0)  # right edge of the frame is the doorway
ROOM, NEAR_EXIT, IN_EXIT = (0.3, 0.2, 0.5, 0.9), (0.6, 0.2, 0.8, 0.9), (0.84, 0.2, 1.0, 0.9)
LEFT_EDGE = (0.0, 0.2, 0.12, 0.9)


class Feed:
    def __init__(self, det):
        self.det, self.t, self.events = det, 0.0, []

    def frames(self, n, *boxes, hold=None, conf=0.9):
        for _ in range(n):
            ev = self.det.feed([(b, conf) for b in boxes], hold, now=self.t)
            if ev:
                self.events.append(ev)
            self.t += 0.2

    def walk_out(self):
        self.frames(5, ROOM)
        self.frames(3, NEAR_EXIT)
        self.frames(3, IN_EXIT)
        self.frames(15)  # 3 s gone


@pytest.fixture
def det():
    d = DepartureDetector(event_gap_seconds=30)
    d.configure(True, EXIT)
    return d


def test_overlap():
    assert overlap(IN_EXIT, EXIT) > 0.9 and overlap(ROOM, EXIT) == 0


def test_walking_out_through_exit_emits_one_departure(det):
    f = Feed(det)
    f.walk_out()
    assert len(f.events) == 1 and f.events[0]["source"] == "detector"
    assert det.state == IDLE and det.events_after(0) == f.events


def test_leaving_view_elsewhere_is_not_a_departure(det):
    f = Feed(det)
    f.frames(5, ROOM)
    f.frames(3, LEFT_EDGE)
    f.frames(20)
    assert f.events == []


def test_walking_around_the_room_is_not_a_departure(det):
    f = Feed(det)
    for _ in range(4):
        f.frames(3, ROOM)
        f.frames(3, NEAR_EXIT)
    assert f.events == []


def test_brief_detection_dropout_at_exit_is_not_a_departure(det):
    f = Feed(det)
    f.frames(5, ROOM)
    f.frames(3, IN_EXIT)
    f.frames(5)  # 1 s missed detections
    f.frames(3, IN_EXIT)
    f.frames(5, ROOM)  # back in the room
    f.frames(20, ROOM)
    assert f.events == []


def test_brief_dropout_mid_room_is_not_a_departure(det):
    f = Feed(det)
    f.frames(5, ROOM)
    f.frames(4)
    f.frames(5, ROOM)
    assert f.events == [] and det.state != IDLE


def test_person_first_seen_inside_exit_zone_must_come_from_the_room(det):
    f = Feed(det)
    f.frames(5, IN_EXIT)  # walked in through the door and stayed there
    f.frames(20)
    assert f.events == []


def test_lingering_at_exit_then_vanishing_late_is_not_a_departure(det):
    f = Feed(det)
    f.frames(5, ROOM)
    f.frames(3, IN_EXIT)
    det._last_at_exit = f.t - 10  # last seen at the exit long before the gap
    f.frames(20)
    assert f.events == []


@pytest.mark.parametrize("reason", ["camera_repositioning", "camera_shift", "camera_dark",
                                    "detection_error"])
def test_holds_suppress_departures(det, reason):
    f = Feed(det)
    f.frames(5, ROOM)
    f.frames(3, IN_EXIT)
    f.frames(15, hold=reason)
    f.frames(15)
    assert f.events == [] and det.status()["hold"] is None


def test_multiple_people_suppress_departures(det):
    f = Feed(det)
    f.frames(5, ROOM)
    f.frames(3, IN_EXIT, ROOM)
    f.frames(15, ROOM)  # one person left; the other is still in the room
    f.frames(15)
    assert f.events == []


def test_camera_gap_restarts_the_sequence(det):
    f = Feed(det)
    f.frames(5, ROOM)
    f.frames(3, IN_EXIT)
    f.t += 5  # no frames for 5 s (camera dropped)
    f.frames(15)
    assert f.events == []


def test_low_confidence_people_are_ignored(det):
    f = Feed(det)
    f.frames(5, ROOM, conf=0.2)
    f.frames(3, IN_EXIT, conf=0.2)
    f.frames(15)
    assert f.events == []


def test_disabled_or_no_zone_never_emits():
    for enabled, zone in [(False, EXIT), (True, None)]:
        d = DepartureDetector()
        d.configure(enabled, zone)
        f = Feed(d)
        f.walk_out()
        assert f.events == []


def test_repeat_departures_are_spaced(det):
    f = Feed(det)
    f.walk_out()
    f.walk_out()  # within 30 s
    assert len(f.events) == 1
    f.t += 31
    f.walk_out()
    assert len(f.events) == 2


def test_invalid_zone_rejected():
    with pytest.raises(ValueError):
        DepartureDetector().configure(True, [0.5, 0.0, 0.2, 1.0])


def test_hold_reason_reads_modes_and_memory():
    class M:
        mode, paused, _suspended_until = "MONITORING", False, None
    assert hold_reason(M(), M(), {}) is None
    m = M()
    m.mode = "CALIBRATING"
    assert hold_reason(m, M(), {}) == "camera_repositioning"
    assert hold_reason(M(), M(), {"camera_shift_at": 100}, now=105) == "camera_shift"
    assert hold_reason(M(), M(), {}, detect_failed=True) == "detection_error"


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
    assert c.put("/api/departures/config", json={"enabled": True, "exit_zone": [2, 0, 3, 1]}).status_code == 422
    cfg = c.put("/api/departures/config", json={"enabled": True, "exit_zone": list(EXIT)}).json()
    assert cfg["enabled"] and cfg["exit_zone"] == list(EXIT)
    c.post("/api/reposition/start")
    assert c.get("/api/departures/context").json()["hold"] == "camera_repositioning"
