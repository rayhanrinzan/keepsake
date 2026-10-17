import numpy as np

from lastseen.config import EngineCfg
from lastseen.engine.touch import TouchWatcher
from lastseen.vision.change import ChangeDetector
from lastseen.vision.geometry import iou

H, W = 360, 640
DT = 0.1
ITEM_W, ITEM_H = 30, 20
HAND = 60
A = (100, 200)   # item top-left spots
B = (300, 200)


def item_box(p):
    return (p[0], p[1], p[0] + ITEM_W, p[1] + ITEM_H)


def hand_box(cx, cy):
    return (cx - HAND // 2, cy - HAND // 2, cx + HAND // 2, cy + HAND // 2)


def centre(p):
    return (p[0] + ITEM_W // 2, p[1] + ITEM_H // 2)


def frame(items=(), hand=None):
    f = np.full((H, W, 3), 100, np.uint8)
    for p in items:
        f[p[1]:p[1] + ITEM_H, p[0]:p[0] + ITEM_W] = 255
    if hand is not None:
        x1, y1, x2, y2 = hand
        f[y1:y2, x1:x2] = (90, 140, 200)
    return f


class Rig:
    def __init__(self, items=(), max_episodes=2):
        self.change = ChangeDetector()
        self.watcher = TouchWatcher(self.change, EngineCfg(), max_episodes=max_episodes)
        self.ts = 0.0
        self.results = []
        self.tick(items, [])

    def tick(self, items=(), hands=(), enabled=True):
        """hands: list of (cx, cy); the first hand is drawn."""
        boxes = [hand_box(*c) for c in hands]
        f = frame(items, boxes[0] if boxes else None)
        for b in boxes[1:]:
            f[b[1]:b[3], b[0]:b[2]] = (90, 140, 200)
        self.change.update(f, boxes, self.ts)
        out = self.watcher.update(f, self.ts, boxes, enabled=enabled)
        self.ts += DT
        self.results += out
        return out

    def repeat(self, n, items=(), hands=()):
        for _ in range(n):
            self.tick(items, hands)


def test_put_down_reports_placed():
    r = Rig()
    r.repeat(10, items=[B], hands=[centre(B)])
    r.repeat(3, items=[B])
    assert len(r.results) == 1
    res = r.results[0]
    assert res.kind == "placed"
    assert iou(res.box, item_box(B)) > 0.5


def test_move_reports_new_spot_not_vacated():
    r = Rig(items=[A])
    ca, cb = centre(A), centre(B)
    r.repeat(5, items=[A], hands=[ca])
    steps = 4
    for i in range(1, steps + 1):
        c = (ca[0] + (cb[0] - ca[0]) * i // steps, ca[1])
        r.tick(items=[], hands=[c])
    r.repeat(5, items=[B], hands=[cb])
    r.repeat(3, items=[B])
    assert len(r.results) == 1
    res = r.results[0]
    assert res.kind == "placed"
    assert iou(res.box, item_box(B)) > 0.5


def test_lift_and_leave_reports_lifted():
    r = Rig(items=[A])
    ca = centre(A)
    r.tick(items=[A], hands=[(ca[0] - 90, ca[1])])
    r.repeat(8, items=[A], hands=[ca])
    for i in range(1, 5):
        r.tick(items=[], hands=[(ca[0] + 60 * i, ca[1])])
    r.repeat(3, items=[])
    assert len(r.results) == 1
    res = r.results[0]
    assert res.kind == "lifted"
    assert iou(res.box, item_box(A)) > 0.5
    assert (res.frame[A[1] + 10, A[0] + 15] == 255).all()


def test_brush_reports_nothing():
    r = Rig(items=[A])
    r.repeat(10, items=[A], hands=[centre(A)])
    r.repeat(3, items=[A])
    assert r.results == []
    assert r.watcher.active() == 0


def test_flicker_ignored():
    r = Rig()
    r.repeat(3, items=[B], hands=[centre(B)])
    r.repeat(3, items=[B])
    assert r.results == []
    assert r.change._refs == {}


def test_single_frame_dropout_does_not_end():
    r = Rig()
    r.repeat(10, items=[B], hands=[centre(B)])
    r.tick(items=[B])
    r.tick(items=[B], hands=[centre(B)])
    assert r.results == []
    assert r.watcher.active() == 1


def test_two_hands_two_episodes():
    r = Rig()
    r.tick(hands=[(100, 100), (500, 250)])
    assert r.watcher.active() == 2
    r.tick(hands=[(105, 100), (495, 250)])
    assert r.watcher.active() == 2


def test_disabled_closes_episodes():
    r = Rig()
    r.repeat(10, items=[B], hands=[centre(B)])
    assert r.watcher.active() == 1
    assert r.tick(items=[B], hands=[centre(B)], enabled=False) == []
    assert r.watcher.active() == 0
    assert r.change._refs == {}


def test_short_move_excludes_vacated_spot_inside_radius():
    # A is only 45 px from the release point (inside near_hand_px) and nearer to it than the new
    # item B, so only the vacated-spot exclusion keeps the result on B.
    a, b = (100, 200), (215, 200)
    r = Rig(items=[a])
    ca, release = centre(a), (160, 210)
    r.repeat(5, items=[a], hands=[ca])
    r.tick(items=[], hands=[(140, 210)])
    r.repeat(5, items=[b], hands=[release])
    r.repeat(3, items=[b])
    assert len(r.results) == 1
    res = r.results[0]
    assert res.kind == "placed"
    assert iou(res.box, item_box(b)) > 0.5
    assert iou(res.box, item_box(a)) < 0.1


def test_blobs_failure_removes_episode():
    class Boom(ChangeDetector):
        def blobs(self, *a, **k):
            raise RuntimeError("boom")

    change = Boom()
    w = TouchWatcher(change, EngineCfg())
    f = frame()
    change.update(f, [], 0.0)
    hb = hand_box(300, 200)
    for i in range(10):
        w.update(f, i * DT, [hb])
    out = []
    for i in range(10, 13):
        out += w.update(f, i * DT, [])
    assert out == []
    assert w.active() == 0
    assert change._refs == {}
