from pathlib import Path

from lastseen.bus import Bus
from lastseen.engine.fake import DESK, TRAY, FakeTracker
from lastseen.memory.store import Store
from tests.fakes import FakeCamera, solid_frame


def make(tmp_path, frame=True):
    bus = Bus()
    store = Store(str(tmp_path / "db.sqlite"), bus)
    cam = FakeCamera(solid_frame(720, 1280) if frame else None)
    return FakeTracker(store, bus, cam, tmp_path / "clips"), store


def test_construction_writes_nothing(tmp_path):
    _, store = make(tmp_path)
    assert store.recent_events(5) == [] and store.list_items() == []


def test_step_once_events_and_item(tmp_path):
    ft, store = make(tmp_path)
    ft.step_once()
    evs = store.recent_events(5)[::-1]
    assert [e["kind"] for e in evs[:2]] == ["PICKED_UP", "PLACED"]
    assert evs[0]["from_zone"] == "tray"
    placed = evs[1]
    assert placed["to_zone"] == "desk" and placed["confidence"] == 0.9
    assert Path(placed["snapshot_path"]).exists()
    assert Path(placed["clip_path"]).exists()
    item = store.get_item("airpods")
    assert item["state"] == "PLACED" and item["zone"] == "desk"
    assert item["bbox"] == list(DESK) and item["last_event_id"] == placed["id"]


def test_second_step_goes_back_to_tray(tmp_path):
    ft, store = make(tmp_path, frame=False)
    ft.step_once()
    ft.step_once()
    evs = store.recent_events(10)[::-1]
    assert [e["kind"] for e in evs] == ["PICKED_UP", "PLACED"] * 2
    assert evs[2]["from_zone"] == "desk" and evs[3]["to_zone"] == "tray"
    assert store.get_item("airpods")["bbox"] == list(TRAY)


def test_stop_before_start_ok(tmp_path):
    ft, _ = make(tmp_path)
    ft.stop()
