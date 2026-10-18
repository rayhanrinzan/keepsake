"""LeaveWatcher + VisionLoop person wiring (no models)."""
import numpy as np

from lastseen.bus import Bus
from lastseen.vision.people import LeaveWatcher
from lastseen.types import Person
from tests.fakes import FakePeople

WH = (1280, 720)


def person(tid, x1, x2, y1=200, y2=500):
    return Person(tid, (x1, y1, x2, y2), ((x1 + x2) // 2, y2))


def watcher(bus=None):
    return LeaveWatcher(WH, edge_frac=0.03, leave_after_s=1.0, bus=bus)


def test_leaving_right_edge_reported_once():
    w, lefts = watcher(), []
    w.update([person(7, 600, 700)], 0.0)
    w.update([person(7, 1000, 1150)], 1.0)
    w.update([person(7, 1150, 1275)], 2.0)
    for i in range(1, 12):
        lefts += w.update([], 2.0 + i * 0.25)[1]
    assert lefts == [7]


def test_missing_mid_frame_is_not_leaving():
    w, lefts = watcher(), []
    w.update([person(7, 550, 700)], 0.0)
    for i in range(1, 16):
        lefts += w.update([], i * 0.25)[1]
    assert lefts == []


def test_short_gap_at_edge_is_not_leaving():
    w = watcher()
    w.update([person(7, 1150, 1275)], 0.0)
    assert w.update([], 0.5) == ([], [])
    assert w.update([person(7, 1150, 1275)], 0.8) == ([], [])
    assert w.update([], 1.2)[1] == []   # new gap just started


def test_new_id_entered():
    w = watcher()
    assert w.update([person(4, 500, 600)], 0.0) == ([4], [])
    assert w.update([person(4, 500, 600)], 0.1) == ([], [])


def test_publishes_messages():
    bus = Bus()
    q = bus.subscribe()
    w = watcher(bus)
    w.update([person(3, 1150, 1278)], 0.0)
    w.update([], 1.5)
    msgs = []
    while not q.empty():
        msgs.append(q.get_nowait())
    assert [(m["type"], m["event"]) for m in msgs] == [("person", "entered_view"), ("person", "left_view")]


def test_forgotten_after_10s_silently():
    w, lefts = watcher(), []
    w.update([person(7, 550, 700)], 0.0)
    for t in (5.0, 11.0, 20.0):
        lefts += w.update([], t)[1]
    assert lefts == [] and w.update([person(7, 550, 700)], 21.0)[0] == [7]


def test_edge_detection_all_sides():
    for box in [(0, 200, 100, 400), (500, 0, 600, 100), (500, 200, 600, 719), (1200, 300, 1280, 400)]:
        w = watcher()
        w.update([Person(1, box, (box[0], box[3]))], 0.0)
        assert w.update([], 1.5)[1] == [1], box


class _Fail:
    def track(self, frame):
        raise RuntimeError("boom")


def test_people_tracker_failure_is_survivable():
    from lastseen.vision.people import safe_track
    persons, dets = safe_track(_Fail(), np.zeros((10, 10, 3), np.uint8))
    assert persons == [] and len(dets) == 0


def test_leave_return_leave_again_reports_twice():
    bus = Bus()
    q = bus.subscribe()
    w, lefts = watcher(bus), []
    w.update([person(7, 1150, 1275)], 0.0)
    lefts += w.update([], 1.5)[1]
    assert w.update([person(7, 1150, 1275)], 3.0) == ([7], [])
    lefts += w.update([], 3.2)[1]
    lefts += w.update([], 4.5)[1]
    assert lefts == [7, 7]
    types = []
    while not q.empty():
        types.append(q.get_nowait()["event"])
    assert types == ["entered_view", "left_view", "entered_view", "left_view"]
