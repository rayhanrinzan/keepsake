import numpy as np

from lastseen.bus import Bus
from lastseen.config import EngineCfg, IdentityCfg
from lastseen.engine.enroll import EnrollSession, enroll_from_click
from lastseen.vision.change import ChangeDetector
from lastseen.vision.geometry import iou
from lastseen.vision.identity import Gallery, Identity
from tests.fakes import FakeEmbedder

H, W = 360, 640
CASE = (300, 200, 340, 230)
CASE2 = (450, 100, 490, 130)
HAND = (260, 160, 300, 200)
HAND_C = (280, 180)
SKIN = (90, 140, 200)


def bg_frame():
    return np.full((H, W, 3), 100, np.uint8)


def paint(f, box, color):
    f[box[1]:box[3], box[0]:box[2]] = color
    return f


def case_frame(*boxes):
    f = bg_frame()
    for b in boxes:
        paint(f, b, 255)
    return f


def hand_frame(case=True):
    f = case_frame(CASE) if case else bg_frame()
    return paint(f, HAND, SKIN)


class Rig:
    def __init__(self, tmp_path, timeout_s=20):
        self.change = ChangeDetector()
        for i in range(3):
            self.change.update(bg_frame(), [], ts=float(i))
        self.bus = Bus()
        self.q = self.bus.subscribe()
        self.emb = FakeEmbedder()
        self.ident = Identity(self.emb, IdentityCfg())
        self.s = EnrollSession("airpods", "AirPods", "airpods case", self.change, self.emb,
                               self.ident, tmp_path, self.bus, EngineCfg(), timeout_s=timeout_s)

    def step(self, frame, ts, hands=(), det=()):
        return self.s.step(frame, ts, list(hands), list(det))


def drive_to_settling(r, frame_after):
    assert r.step(hand_frame(), 10.0, [HAND]) == "waiting_putdown"
    assert r.step(hand_frame(), 10.3, [HAND]) == "waiting_putdown"
    assert r.step(hand_frame(), 10.7, [HAND]) == "waiting_putdown"
    assert r.step(frame_after, 10.8) == "waiting_putdown"
    assert r.step(frame_after, 10.9) == "waiting_putdown"
    assert r.step(frame_after, 11.0) == "settling"


def test_enroll_pickup_putdown_saves_gallery(tmp_path):
    r = Rig(tmp_path)
    assert r.step(bg_frame(), 9.0) == "waiting_pickup"
    drive_to_settling(r, case_frame(CASE))
    stages = [r.step(case_frame(CASE), 11.0 + 0.2 * (i + 1)) for i in range(8)]
    assert stages[-1] == "done"
    g = Gallery.load("airpods", tmp_path)
    assert len(g.pos) == 8 and g.meta["origin"] == "enrolled" and g.template is not None
    assert g.meta["display_name"] == "AirPods"
    box, g2 = r.s.result()
    assert iou(box, CASE) > 0.5
    assert r.emb.calls == 2  # one jitter embed + one negatives embed
    assert r.change._refs == {}  # ref dropped


def test_two_blobs_fails(tmp_path):
    r = Rig(tmp_path)
    r.step(hand_frame(), 10.0, [HAND])
    r.step(hand_frame(), 10.7, [HAND])
    two = case_frame(CASE, (240, 220, 280, 250))
    r.step(two, 10.8)
    r.step(two, 10.9)
    assert r.step(two, 11.0) == "failed"
    assert r.s.message.startswith("I couldn't tell which thing")
    assert Gallery.load("airpods", tmp_path) is None
    assert r.change._refs == {}


def test_zero_blobs_fails(tmp_path):
    r = Rig(tmp_path)
    r.step(hand_frame(False), 10.0, [HAND])
    r.step(hand_frame(False), 10.7, [HAND])
    r.step(bg_frame(), 10.8)
    r.step(bg_frame(), 10.9)
    assert r.step(bg_frame(), 11.0) == "failed"


def test_timeout_fails(tmp_path):
    r = Rig(tmp_path)
    assert r.step(bg_frame(), 0.0) == "waiting_pickup"
    assert r.step(bg_frame(), 21.0) == "failed"
    assert r.s.message == "I didn't see anything being put down — let's try again."
    assert r.change._refs == {}


def test_single_frame_dropout_ignored(tmp_path):
    r = Rig(tmp_path)
    r.step(hand_frame(), 10.0, [HAND])
    r.step(hand_frame(), 11.0, [HAND])
    # two blobs would fail if a search ran; dropout steps must not search
    two = case_frame(CASE, (240, 220, 280, 250))
    assert r.step(two, 11.1) == "waiting_putdown"
    assert r.step(hand_frame(), 11.2, [HAND]) == "waiting_putdown"
    assert r.step(case_frame(CASE), 11.3) == "waiting_putdown"
    assert r.step(case_frame(CASE), 11.4) == "waiting_putdown"
    assert r.step(case_frame(CASE), 11.5) == "settling"


def test_finalize_error_fails_and_drops_ref(tmp_path):
    r = Rig(tmp_path)
    drive_to_settling(r, case_frame(CASE))

    def boom(*a, **k):
        raise RuntimeError("embed down")
    r.emb.embed = boom
    out = [r.step(case_frame(CASE), 11.2 + 0.2 * i) for i in range(8)]
    assert out[-1] == "failed"
    assert r.s.message == "Something went wrong saving it — let's try again."
    assert r.change._refs == {}


def test_close_cancels_and_is_idempotent(tmp_path):
    r = Rig(tmp_path)
    r.step(hand_frame(), 10.0, [HAND])
    r.s.close()
    assert r.s.stage == "failed" and r.s.message == "Enrollment cancelled."
    assert r.change._refs == {}
    n = r.q.qsize()
    r.s.close()
    assert r.q.qsize() == n


def test_click_default_ts_is_now(tmp_path):
    import time
    change = ChangeDetector()
    change.update(bg_frame(), [], ts=0.0)
    emb = FakeEmbedder()
    _, g = enroll_from_click(bg_frame(), "x", "X", 100, 100, change=change, embedder=emb,
                             identity=Identity(emb, IdentityCfg()), gallery_root=tmp_path)
    assert abs(g.meta["created_ts"] - time.time()) < 5


def test_hand_reappearing_returns_to_putdown(tmp_path):
    r = Rig(tmp_path)
    r.step(hand_frame(), 10.0, [HAND])
    r.step(hand_frame(), 10.7, [HAND])
    r.step(case_frame(CASE), 10.8)
    r.step(case_frame(CASE), 10.9)
    assert r.step(case_frame(CASE), 11.0) == "settling"
    assert r.step(hand_frame(), 11.2, [HAND]) == "waiting_putdown"
    assert r.step(hand_frame(), 11.9, [HAND]) == "waiting_putdown"
    r.step(case_frame(CASE), 12.0)
    r.step(case_frame(CASE), 12.1)
    assert r.step(case_frame(CASE), 12.2) == "settling"


def test_blob_vanishing_while_settling_fails(tmp_path):
    r = Rig(tmp_path)
    drive_to_settling(r, case_frame(CASE))
    out = [r.step(bg_frame(), 12.0 + i) for i in range(8)]
    assert out[-1] == "failed"
    assert r.s.message == "I lost track of it — try again a bit more in the open"
    assert r.change._refs == {}


def test_terminal_state_sticky(tmp_path):
    r = Rig(tmp_path)
    r.step(bg_frame(), 0.0)
    assert r.step(bg_frame(), 21.0) == "failed"
    n = r.q.qsize()
    assert r.step(hand_frame(), 22.0, [HAND]) == "failed"
    assert r.q.qsize() == n


def test_status_messages_in_order(tmp_path):
    r = Rig(tmp_path)
    drive_to_settling(r, case_frame(CASE))
    for i in range(8):
        r.step(case_frame(CASE), 11.2 + 0.2 * i)
    msgs = []
    while not r.q.empty():
        m = r.q.get_nowait()
        assert m["type"] == "enroll_status" and m["item_id"] == "airpods"
        msgs.append((m["stage"], m["message"]))
    assert msgs == [
        ("waiting_pickup", "OK, pick it up and put it down where I can see it."),
        ("waiting_putdown", "Now put it down where I can see it."),
        ("settling", "Hold on, taking a look."),
        ("done", "Got it. I'll remember your AirPods."),
    ]
    assert r.s.message == "Got it. I'll remember your AirPods."


def test_detector_box_unioned(tmp_path):
    r = Rig(tmp_path)
    drive_to_settling(r, case_frame(CASE))
    det = (296, 196, 346, 236)
    for i in range(8):
        r.step(case_frame(CASE), 11.2 + 0.2 * i, det=[det])
    box, _ = r.s.result()
    assert box[0] <= 296 and box[2] >= 346


def test_click_enroll(tmp_path):
    change = ChangeDetector()
    change.update(bg_frame(), [], ts=0.0)
    emb = FakeEmbedder()
    out = enroll_from_click(case_frame(CASE), "airpods", "AirPods", 320, 215, change=change,
                            embedder=emb, identity=Identity(emb, IdentityCfg()),
                            gallery_root=tmp_path)
    box, g = out
    assert iou(box, CASE) > 0.5 and len(g.pos) == 8
    assert Gallery.load("airpods", tmp_path).meta["origin"] == "enrolled"


def test_click_fallback_box_and_outside(tmp_path):
    change = ChangeDetector()
    change.update(bg_frame(), [], ts=0.0)
    emb = FakeEmbedder()
    kw = dict(change=change, embedder=emb, identity=Identity(emb, IdentityCfg()),
              gallery_root=tmp_path)
    box, _ = enroll_from_click(bg_frame(), "x", "X", 100, 100, **kw)
    assert box == (70, 70, 130, 130)
    assert enroll_from_click(bg_frame(), "x", "X", -5, 10, **kw) is None
    assert enroll_from_click(bg_frame(), "x", "X", 640, 10, **kw) is None
