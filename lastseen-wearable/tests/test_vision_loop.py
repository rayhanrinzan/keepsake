"""VisionLoop wiring with fakes only (no models). tick() is called directly except in the thread test."""
import logging
import time
from pathlib import Path

import numpy as np

from lastseen.bus import Bus
from lastseen.capture.ringbuffer import RingBuffer
from lastseen.config import Config, DetectorCfg, ItemCfg, PathsCfg, WearableCfg
from lastseen.engine.vision_loop import VisionLoop
from lastseen.engine.zones import Zone, ZoneMap
from lastseen.memory.store import Store
from lastseen.vision.change import ChangeDetector
from lastseen.vision.identity import Gallery
from lastseen.types import Person
from lastseen.engine.touch import TouchResult, TouchWatcher
from lastseen.vision.classify import Classification
from tests.fakes import (FakeCamera, FakeClassifier, FakeDetector, FakeEmbedder, FakeHands, FakePeople,
                         FakeTouch)

H, W = 360, 640
WH = (W, H)
TRAY_CASE = (420, 250, 460, 280)   # bottom-center (440, 280) -> tray
DESK_CASE = (120, 250, 160, 280)   # bottom-center (140, 280) -> desk
SKIN = (90, 140, 200)
DT = 0.125
T0 = 1000.0
PLACED_AT = WearableCfg().placed_hits - 1   # rest tick (0-based) on which a released item counts as put down


def rect(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


ZONES = ZoneMap([
    Zone("desk", "surface", rect(0.05, 0.45, 0.45, 0.9)),
    Zone("tray", "surface", rect(0.55, 0.45, 0.85, 0.9)),
])


def bg():
    return np.full((H, W, 3), 100, np.uint8)


def paint(f, box, color):
    f[box[1]:box[3], box[0]:box[2]] = color
    return f


def at(cx, cy, w=40, h=30):
    return (cx - w // 2, cy - h // 2, cx + w // 2, cy + h // 2)


def hand_at(cx, cy, s=60):
    return (cx - s // 2, cy - s // 2, cx + s // 2, cy + s // 2)


def scene(case=None, hand=None):
    f = bg()
    if hand is not None:
        paint(f, hand, SKIN)
    if case is not None:
        paint(f, case, 255)
    return f


def make_cfg(tmp_path, items=("airpods",), every_n=1):
    return Config(items=[ItemCfg(id=i, display_name=i.title(), prompt=i) for i in items],
                  detector=DetectorCfg(every_n=every_n), paths=PathsCfg(data=str(tmp_path)),
                  device="cpu")


def save_gallery(tmp_path, item_id="airpods", box=TRAY_CASE, empty=False):
    g = Gallery(item_id, tmp_path / "gallery")
    if not empty:
        frame = scene(case=box)
        g.pos = FakeEmbedder().embed(frame, [box])
        g.neg = FakeEmbedder().embed(frame, [(20, 20, 60, 50), (560, 20, 600, 50)])
    g.save()
    return g


class Rig:
    def __init__(self, tmp_path, items=("airpods",), every_n=1, zones=ZONES, hands=None,
                 detector=None, placed_on_tray=True, classifier=None, touch=None):
        self.cfg = make_cfg(tmp_path, items, every_n)
        self.bus = Bus()
        self.store = Store(str(tmp_path / "db.sqlite"), self.bus)
        if placed_on_tray:
            self.store.upsert_item("airpods", "AirPods", False, "PLACED", "tray", TRAY_CASE, 0.9, T0 - 10)
        self.det = detector or FakeDetector()
        self.hands = hands or FakeHands()
        self.emb = FakeEmbedder()
        self.ring = RingBuffer()
        self.clips = tmp_path / "clips"
        self.change = ChangeDetector()
        if touch == "real":
            touch = TouchWatcher(self.change, self.cfg.engine)
        self.touch, self.classifier = touch, classifier
        self.loop = VisionLoop(self.cfg, FakeCamera(), self.ring, self.store, self.bus, zones,
                               self.det, self.hands, self.emb, self.change, self.clips,
                               classifier=classifier, touch=touch)


# ---------------------------------------------------------------- integration: pick up -> place
def pickup_place_sequence():
    """(frame, ts, hands, det boxes) per tick: case on tray, hand picks it up, carries it, sets it on desk."""
    seq = []
    t = T0
    def add(frame, hands, case):
        nonlocal t
        seq.append((frame, t, hands, [("airpods", case, 0.3)] if case else []))
        t += DT
    for _ in range(6):                                   # resting on the tray
        add(scene(TRAY_CASE), [], TRAY_CASE)
    h = hand_at(440, 265)
    for _ in range(4):                                   # hand on the case
        add(scene(TRAY_CASE, h), [h], TRAY_CASE)
    for cx in (365, 290, 215, 140):                      # carried left, case in hand
        c, hb = at(cx, 265), hand_at(cx, 265)
        add(scene(c, hb), [hb], c)
    hb = hand_at(140, 215)                               # hand lifts off, case stays on desk
    add(scene(DESK_CASE, hb), [hb], DESK_CASE)
    for _ in range(9):                                   # case alone on the desk
        add(scene(DESK_CASE), [], DESK_CASE)
    return seq


def scripted_rig(tmp_path, seq, **kw):
    hands_by_ms = {int(ts * 1000): hands for _, ts, hands, _ in seq}
    dets = {}
    hands = FakeHands(fn=lambda frame, ts_ms: hands_by_ms.get(int(ts_ms), []))
    det = FakeDetector(fn=lambda frame: dets["now"])
    r = Rig(tmp_path, hands=hands, detector=det, **kw)
    return r, dets


def run(r, dets, seq):
    for frame, ts, _, d in seq:
        dets["now"] = d
        r.loop.tick(frame, ts)


def test_loop_logs_pickup_and_place(tmp_path):
    save_gallery(tmp_path)
    seq = pickup_place_sequence()
    r, dets = scripted_rig(tmp_path, seq)
    run(r, dets, seq)
    events = r.store.recent_events(10)[::-1]
    assert [e["kind"] for e in events] == ["PICKED_UP", "PLACED"]
    item = r.store.get_item("airpods")
    assert item["zone"] == "desk" and item["state"] == "PLACED"
    placed = events[-1]
    assert placed["to_zone"] == "desk" and placed["from_zone"] == "tray"
    assert Path(placed["snapshot_path"]).exists()
    assert Path(placed["snapshot_path"]).parent == r.clips
    assert item["last_event_id"] == placed["id"]
    assert r.loop.metrics["last_event_ts"] == placed["ts"]
    assert r.loop.trackers["airpods"].state == "PLACED"


def test_no_clip_when_clips_disabled(tmp_path):
    save_gallery(tmp_path)
    seq = pickup_place_sequence()
    r, dets = scripted_rig(tmp_path, seq)
    r.cfg.features.clips = False
    run(r, dets, seq)
    placed = r.store.recent_events(10)[0]
    assert placed["kind"] == "PLACED"
    assert Path(placed["snapshot_path"]).exists() and placed["clip_path"] is None


def test_one_embed_call_per_tick(tmp_path):
    save_gallery(tmp_path)
    save_gallery(tmp_path, "glasses", box=DESK_CASE)
    seq = pickup_place_sequence()
    r, dets = scripted_rig(tmp_path, seq, items=("airpods", "glasses"))
    assert set(r.loop.trackers) == {"airpods", "glasses"}
    for frame, ts, _, d in seq:
        dets["now"] = d
        before = r.emb.calls
        r.loop.tick(frame, ts)
        assert r.emb.calls - before <= 1


def test_tick_survives_exception(tmp_path):
    save_gallery(tmp_path)
    r = Rig(tmp_path, hands=FakeHands(raise_on=0))
    for i in range(4):
        r.loop.tick(scene(TRAY_CASE), T0 + i * DT)
    assert r.hands.calls >= 2              # tick 0 raised, a later tick ran hands again
    assert r.loop.metrics["hands_ms"] is not None
    assert r.loop.metrics["vision_tps"] > 0
    assert r.det.calls >= 3                # the detector kept running after the failing tick


def test_hands_every_second_tick_when_idle(tmp_path):
    save_gallery(tmp_path)
    r = Rig(tmp_path)
    for i in range(10):
        r.loop.tick(scene(TRAY_CASE), T0 + i * DT)
    assert r.hands.calls == 5


def test_detector_every_n_ticks(tmp_path):
    save_gallery(tmp_path)
    r = Rig(tmp_path, every_n=3)
    for i in range(9):
        r.loop.tick(scene(TRAY_CASE), T0 + i * DT)
    assert r.det.calls == 3
    assert r.loop.metrics["detector_ms"] is not None


def test_no_tracker_without_gallery(tmp_path):
    save_gallery(tmp_path)
    save_gallery(tmp_path, "water_bottle", empty=True)
    r = Rig(tmp_path, items=("airpods", "glasses", "water_bottle"))
    assert set(r.loop.trackers) == {"airpods"}
    for i in range(3):
        r.loop.tick(scene(TRAY_CASE), T0 + i * DT)
    rows = {it["id"]: it for it in r.store.list_items()}
    assert rows["glasses"]["state"] == "UNKNOWN" and rows["water_bottle"]["state"] == "UNKNOWN"
    assert rows["airpods"]["state"] == "PLACED"          # existing row never overwritten
    assert r.loop.trackers["airpods"].state == "PLACED"  # restored from the store


def test_privacy_mask_blacks_out_before_processing(tmp_path):
    save_gallery(tmp_path)
    zones = ZoneMap(ZONES.zones + [Zone("window", "privacy", rect(0.0, 0.0, 0.25, 0.25))])
    r = Rig(tmp_path, zones=zones)
    frame = np.full((H, W, 3), 220, np.uint8)
    r.loop.tick(frame, T0)
    seen = r.det.frames[0]
    assert seen[:80, :150].max() == 0          # privacy region blacked out
    assert seen[300:, 300:].min() == 220        # rest untouched
    assert frame.min() == 220                   # caller's (shared) frame not modified
    assert r.ring.window(0, 1e12)[0][1][:80, :150].max() == 0


def test_overlay_returns_new_image(tmp_path):
    save_gallery(tmp_path)
    r = Rig(tmp_path)
    r.loop.tick(scene(TRAY_CASE), T0)
    frame = scene(TRAY_CASE)
    orig = frame.copy()
    out = r.loop.overlay(frame)
    assert out is not frame and out.shape == frame.shape
    assert np.array_equal(frame, orig)
    assert not np.array_equal(out, orig)


# ---------------------------------------------------------------- enrollment
def enroll_sequence():
    case, hand = (150, 230, 190, 260), (110, 190, 150, 230)  # case on the desk
    seq, t = [], T0
    for _ in range(3):
        seq.append((bg(), t, [])); t += DT
    for _ in range(6):
        seq.append((paint(scene(case), hand, SKIN), t, [hand])); t += DT
    for _ in range(12):
        seq.append((scene(case), t, [])); t += DT
    return seq, case


def test_start_enroll_creates_tracker_and_placed_event(tmp_path):
    seq, case = enroll_sequence()
    hands_by_ms = {int(ts * 1000): h for _, ts, h in seq}
    r = Rig(tmp_path, hands=FakeHands(fn=lambda f, ms: hands_by_ms.get(int(ms), [])),
            placed_on_tray=False)
    assert "wallet" not in r.loop.trackers
    assert r.loop.start_enroll("wallet", "Wallet") == {"ok": True, "item_id": "wallet"}
    for frame, ts, _ in seq:
        r.loop.tick(frame, ts)
    assert r.loop.trackers["wallet"].state == "PLACED"
    ev = r.store.recent_events(5)[0]
    assert ev["kind"] == "PLACED" and ev["item_id"] == "wallet" and ev["confidence"] == 0.9
    assert ev["to_zone"] == "desk" and Path(ev["snapshot_path"]).exists()
    item = r.store.get_item("wallet")
    assert item["display_name"] == "Wallet" and item["state"] == "PLACED"
    assert any(i.id == "wallet" for i in r.cfg.items)      # new item added at runtime
    assert "wallet" in r.det.items_set[-1]                  # detector re-prompted
    assert Gallery.load("wallet", tmp_path / "gallery") is not None


def test_click_enroll(tmp_path):
    r = Rig(tmp_path, placed_on_tray=False)
    for i in range(3):
        r.loop.tick(bg(), T0 + i * DT)
    r.loop.tick(scene(DESK_CASE), T0 + 3 * DT)
    res = r.loop.click_enroll("keys", "Keys", 140, 265)
    assert res["ok"] is True
    assert r.loop.trackers["keys"].state == "PLACED"
    assert r.store.get_item("keys")["zone"] == "desk"
    assert r.store.recent_events(1)[0]["kind"] == "PLACED"
    assert r.loop.click_enroll("keys", "Keys", 5000, 5000)["ok"] is False


# ---------------------------------------------------------------- thread
def test_thread_start_stop(tmp_path):
    save_gallery(tmp_path)
    r = Rig(tmp_path)
    r.loop.camera = FakeCamera(frame=scene(TRAY_CASE))
    r.loop.start()
    time.sleep(0.5)
    r.loop.stop()
    assert not r.loop.is_alive()
    assert r.loop.metrics["vision_tps"] > 0


# ---------------------------------------------------------------- people / leaving view (Task 11b)
def _held_rig(tmp_path, people, every_n=1):
    save_gallery(tmp_path)
    h = hand_at(440, 265)
    seq = [(scene(TRAY_CASE), T0 + i * DT, [], [("airpods", TRAY_CASE, 0.3)]) for i in range(6)]
    n0 = len(seq)
    seq += [(scene(TRAY_CASE, h), T0 + (n0 + i) * DT, [h], [("airpods", TRAY_CASE, 0.3)]) for i in range(4)]
    up = hand_at(440, 185)  # lifted off the tray: the case is gone from its spot -> PICKED_UP
    n1 = len(seq)
    seq += [(scene(None, up), T0 + (n1 + i) * DT, [up], []) for i in range(20)]
    r, dets = scripted_rig(tmp_path, seq)
    r.cfg.persons.every_n = every_n
    r.loop.people = people
    return r, dets, seq


def _edge_person(tid=5):
    return Person(tid, (560, 100, 639, 330), (600, 330))


def test_holder_leaving_view_carries_out(tmp_path):
    # person present for the first 5 people-calls after the pickup begins, then gone
    script = [[]] * 6 + [[_edge_person()]] * 6 + [[]]
    r, dets, seq = _held_rig(tmp_path, FakePeople(script))
    run(r, dets, seq)
    events = [e["kind"] for e in r.store.recent_events(10)[::-1]]
    assert events == ["PICKED_UP", "CARRIED_OUT"]
    assert r.loop.trackers["airpods"].state == "CARRIED_OUT"


def test_people_in_between_ticks_and_left_view_once(tmp_path):
    p = _edge_person()
    script = [[]] * 3 + [[p]] * 4 + [[]]
    r, dets, seq = _held_rig(tmp_path, FakePeople(script), every_n=2)
    seen = []
    t = r.loop.trackers["airpods"]
    orig = t.step

    def spy(obs):
        seen.append((len(obs.persons), list(obs.left_view)))
        return orig(obs)
    t.step = spy
    run(r, dets, seq)
    assert r.loop.people.calls == (len(seq) + 1) // 2
    assert any(n == 1 for n, _ in seen[10:])                    # persons carried across in-between ticks
    lv = [x for _, x in seen if x]
    assert lv == [[5]]                                           # reported on exactly one tick


def test_people_tracker_exception_does_not_break_tick(tmp_path):
    class Boom:
        def track(self, frame):
            raise RuntimeError("boom")
    r, dets, seq = _held_rig(tmp_path, Boom())
    run(r, dets, seq)
    assert r.loop.trackers["airpods"].state in ("HELD", "UNKNOWN")
    assert [e["kind"] for e in r.store.recent_events(10)[::-1]][0] == "PICKED_UP"


def test_overlay_draws_persons(tmp_path):
    r, dets, seq = _held_rig(tmp_path, FakePeople([[Person(2, (50, 50, 150, 300), (100, 300))]]))
    run(r, dets, seq[:3])
    out = r.loop.overlay(bg())
    assert out.shape == (H, W, 3) and (out != bg()).any()


def test_failing_tracker_does_not_stop_others(tmp_path):
    save_gallery(tmp_path, "airpods")
    save_gallery(tmp_path, "keys")
    r = Rig(tmp_path, items=("airpods", "keys"))
    r.store.upsert_item("keys", "Keys", False, "PLACED", "desk", DESK_CASE, 0.9, T0 - 10)
    r.loop._make_tracker("keys", r.store.get_item("keys"))
    r.loop.galleries["keys"] = Gallery.load("keys", tmp_path / "gallery")

    def bad(obs):
        raise RuntimeError("tracker boom")
    r.loop.trackers["airpods"].step = bad
    ok = r.loop.trackers["keys"]
    orig = ok.step
    called = []
    ok.step = lambda obs: (called.append(1), orig(obs))[1]
    r.loop._view = {"hands": [], "items": [("sentinel",)]}
    r.loop.tick(bg(), T0)
    assert called
    assert r.loop._view["items"] != [("sentinel",)]


def test_enroll_existing_config_item_keeps_display_name(tmp_path):
    seq, case = enroll_sequence()
    hands_by_ms = {int(ts * 1000): h for _, ts, h in seq}
    r = Rig(tmp_path, hands=FakeHands(fn=lambda f, ms: hands_by_ms.get(int(ms), [])))
    old = r.loop.trackers.get("airpods")
    assert r.loop.start_enroll("airpods", "")["ok"] is True
    for frame, ts, _ in seq:
        r.loop.tick(frame, ts)
    assert r.loop.trackers["airpods"] is not old
    assert r.loop.trackers["airpods"].state == "PLACED"
    ev = r.store.recent_events(5)[0]
    assert ev["kind"] == "PLACED" and ev["item_id"] == "airpods" and ev["confidence"] == 0.9
    assert r.store.get_item("airpods")["display_name"] == "Airpods"   # config name kept
    assert [i.id for i in r.cfg.items].count("airpods") == 1


def test_leave_watcher_failure_does_not_stop_trackers(tmp_path):
    r, dets, seq = _held_rig(tmp_path, FakePeople([[_edge_person()]]))

    class BadWatcher:
        w, h = W, H
        def update(self, persons, ts):
            raise RuntimeError("watcher boom")
    r.loop._watcher = BadWatcher()
    run(r, dets, seq)
    assert [e["kind"] for e in r.store.recent_events(10)[::-1]][0] == "PICKED_UP"


# ---------------------------------------------------------------- touch-to-track (Task 4)
ITEMS2 = ("airpods", "glasses")


def sure(item_id, p=0.97):
    def fn(frame, box, det_item_ids, candidates):
        probs = {c: (p if c == item_id else 0.01) for c in candidates}
        probs["other"] = 0.02
        return Classification(item_id, probs, "ok")
    return fn


def first_candidate(frame, box, det_item_ids, candidates):
    return Classification(candidates[0], {candidates[0]: 0.9, "other": 0.1}, "ok")


def touch_rig(tmp_path, script, classifier=None, **kw):
    kw.setdefault("items", ITEMS2)
    kw.setdefault("placed_on_tray", False)
    return Rig(tmp_path, touch=FakeTouch(script), classifier=classifier or FakeClassifier(sure("airpods")),
               **kw)


def placed_result(box=DESK_CASE, ts=T0):
    return TouchResult("placed", box, scene(box), ts, (int(_center_of(box)[0]), int(_center_of(box)[1])))


def _center_of(b):
    return ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)


def test_touch_locks_untracked_item(tmp_path, caplog):
    caplog.set_level(logging.INFO)
    seq, case = enroll_sequence()
    hands_by_ms = {int(ts * 1000): h for _, ts, h in seq}
    clf = FakeClassifier(sure("airpods"))
    r = Rig(tmp_path, items=ITEMS2, placed_on_tray=False, touch="real", classifier=clf,
            hands=FakeHands(fn=lambda f, ms: hands_by_ms.get(int(ms), [])))
    for frame, ts, _ in seq:
        r.loop.tick(frame, ts)
    assert len(clf.calls) == 1
    box, _, candidates = clf.calls[0]
    assert candidates == ["airpods", "glasses"]          # all configured items
    assert set(r.loop.trackers) == {"airpods"}
    assert r.loop.trackers["airpods"].state == "PLACED"
    events = r.store.recent_events(10)
    assert [e["kind"] for e in events] == ["PLACED"]
    assert events[0]["confidence"] == 0.97 and events[0]["to_zone"] == "desk"
    assert Path(events[0]["snapshot_path"]).exists()
    assert Gallery.load("airpods", tmp_path / "gallery").meta["origin"] == "auto"
    assert r.store.get_item("airpods")["state"] == "PLACED"
    assert "touch: locked airpods (p=0.97)" in caplog.text


def test_touch_unsure_locks_nothing(tmp_path, caplog):
    caplog.set_level(logging.INFO)
    clf = FakeClassifier(lambda f, b, d, c: Classification(
        None, {"airpods": 0.401, "glasses": 0.35, "other": 0.249}, "close"))
    r = touch_rig(tmp_path, [[placed_result()]], classifier=clf)
    r.loop.tick(bg(), T0)
    assert len(clf.calls) == 1
    assert r.loop.trackers == {} and r.store.recent_events(5) == []
    assert "touch: not locking (close)" in caplog.text
    assert "0.4" in caplog.text and "0.401" not in caplog.text   # probs rounded to 2


def test_touch_on_tracked_item_ignored(tmp_path):
    save_gallery(tmp_path)                               # airpods tracked, PLACED on the tray
    clf = FakeClassifier(sure("glasses"))
    r = touch_rig(tmp_path, [[placed_result(TRAY_CASE)]], classifier=clf, placed_on_tray=True)
    r.loop.tick(scene(TRAY_CASE), T0)
    assert clf.calls == []
    assert set(r.loop.trackers) == {"airpods"}


def test_touch_all_items_tracked_classifies_but_does_not_lock(tmp_path, caplog):
    caplog.set_level(logging.INFO)
    save_gallery(tmp_path)
    clf = FakeClassifier(sure("airpods"))
    r = touch_rig(tmp_path, [[placed_result(DESK_CASE)]], classifier=clf, items=("airpods",),
                  placed_on_tray=True)
    old = r.loop.trackers["airpods"]
    r.loop.tick(scene(TRAY_CASE), T0)
    assert len(clf.calls) == 1 and clf.calls[0][2] == ["airpods"]
    assert "touch: already tracked airpods" in caplog.text
    assert set(r.loop.trackers) == {"airpods"} and r.loop.trackers["airpods"] is old
    assert r.store.recent_events(5) == []


def test_touch_top_item_tracked_other_untracked_no_lock(tmp_path, caplog):
    caplog.set_level(logging.INFO)
    save_gallery(tmp_path)                               # airpods tracked on the tray; glasses untracked
    clf = FakeClassifier(sure("airpods"))
    r = touch_rig(tmp_path, [[placed_result(DESK_CASE)]], classifier=clf, placed_on_tray=True)
    r.loop.tick(scene(TRAY_CASE), T0)
    assert len(clf.calls) == 1 and clf.calls[0][2] == ["airpods", "glasses"]
    assert "touch: already tracked airpods" in caplog.text
    assert set(r.loop.trackers) == {"airpods"} and r.store.recent_events(5) == []


def test_one_lock_per_tick(tmp_path):
    save_gallery(tmp_path)                               # airpods tracked on the tray
    clf = FakeClassifier(sure("glasses"))
    far = at(300, 100)
    r = touch_rig(tmp_path, [[placed_result(TRAY_CASE), placed_result(DESK_CASE), placed_result(far)]],
                  classifier=clf, items=("airpods", "glasses", "keys"), placed_on_tray=True)
    r.loop.tick(scene(TRAY_CASE), T0)
    assert [b for b, _, _ in clf.calls] == [DESK_CASE]   # tracked overlap skipped; third never classified
    assert set(r.loop.trackers) == {"airpods", "glasses"}
    assert r.loop.trackers["glasses"].bbox == DESK_CASE


def test_touch_suppressed_during_enroll(tmp_path):
    r = touch_rig(tmp_path, [])
    r.loop.tick(bg(), T0)
    r.loop.start_enroll("wallet", "Wallet")
    r.loop.tick(bg(), T0 + DT)
    assert r.touch.enabled == [True, False]


def test_touch_off_by_flag(tmp_path):
    clf = FakeClassifier(sure("airpods"))
    r = touch_rig(tmp_path, [[placed_result()]], classifier=clf)
    r.cfg.features.touch_to_track = False
    r.loop.tick(bg(), T0)
    assert clf.calls == [] and r.loop.trackers == {}
    assert True not in r.touch.enabled


def test_touch_failure_is_isolated(tmp_path):
    def boom(*a):
        raise RuntimeError("classifier boom")
    r = touch_rig(tmp_path, [[placed_result()]], classifier=FakeClassifier(boom))
    r.loop.tick(bg(), T0)
    assert r.loop._view["items"] == [] and r.loop.metrics["vision_tps"] >= 0
    assert r.ring.window(0, 1e12)                         # tick went on past the touch step


def lifted_result(last_hand, box=DESK_CASE, ts=T0):
    return TouchResult("lifted", box, scene(box), ts, last_hand)


def test_lifted_ignores_current_detections(tmp_path):
    clf = FakeClassifier(sure("airpods"))
    wide = (115, 245, 165, 285)                          # current-frame det overlapping the vacated spot
    r = touch_rig(tmp_path, [[lifted_result((300, 200))]], classifier=clf,
                  detector=FakeDetector(fn=lambda f: [("airpods", wide, 0.3)]))
    r.loop.tick(bg(), T0)
    assert clf.calls[0][1] == []
    assert r.loop.trackers["airpods"].bbox == DESK_CASE  # box not widened by the stale detection


def test_placed_uses_current_detections(tmp_path):
    clf = FakeClassifier(sure("airpods"))
    r = touch_rig(tmp_path, [[placed_result()]], classifier=clf,
                  detector=FakeDetector(fn=lambda f: [("airpods", DESK_CASE, 0.3)]))
    r.loop.tick(scene(DESK_CASE), T0)
    assert clf.calls[0][1] == ["airpods"]


def test_lifted_at_edge_is_carried_out(tmp_path):
    r = touch_rig(tmp_path, [[lifted_result((636, 200))]])
    r.loop.tick(bg(), T0)
    ev = r.store.recent_events(5)
    assert [e["kind"] for e in ev] == ["CARRIED_OUT"]
    assert ev[0]["to_zone"] is None and ev[0]["from_zone"] == "desk"
    assert ev[0]["confidence"] == 0.97
    snap = Path(ev[0]["snapshot_path"])
    assert snap.exists()
    import cv2
    img = cv2.imread(str(snap))
    cx, cy = (int(v) for v in _center_of(DESK_CASE))
    assert img[cy, cx].min() > 200                       # snapshot drawn from the before frame
    assert r.loop.trackers["airpods"].state == "CARRIED_OUT"
    assert r.store.get_item("airpods")["state"] == "CARRIED_OUT"


def test_lifted_in_view_is_held(tmp_path):
    r = touch_rig(tmp_path, [[lifted_result((300, 200))]])
    r.loop.tick(bg(), T0)
    ev = r.store.recent_events(5)
    assert [e["kind"] for e in ev] == ["PICKED_UP"]
    assert ev[0]["from_zone"] == "desk"
    t = r.loop.trackers["airpods"]
    assert t.state == "HELD" and t.hand_anchor() == (300, 200)
    assert r.store.get_item("airpods")["state"] == "HELD"
    assert Gallery.load("airpods", tmp_path / "gallery").meta["origin"] == "auto"


def test_forget_removes_tracker_and_gallery(tmp_path):
    r = touch_rig(tmp_path, [[placed_result()]])
    r.loop.tick(bg(), T0)
    assert "airpods" in r.loop.trackers and (tmp_path / "gallery" / "airpods").is_dir()
    assert r.loop.forget("airpods") == {"ok": True}
    assert "airpods" not in r.loop.trackers and "airpods" not in r.loop.galleries
    assert not (tmp_path / "gallery" / "airpods").exists()
    row = r.store.get_item("airpods")
    assert row["state"] == "UNKNOWN" and row["zone"] is None and row["bbox"] is None
    r.loop.tick(bg(), T0 + DT)                           # loop keeps running without it
    assert r.loop.forget("nope") == {"ok": False}
    assert r.loop.forget("../airpods") == {"ok": False}
    assert (tmp_path / "gallery").is_dir()


def test_forget_queued_to_running_thread(tmp_path):
    r = touch_rig(tmp_path, [[placed_result()]])
    r.loop.tick(bg(), T0)
    r.loop.camera = FakeCamera(frame=bg())
    r.loop.start()
    try:
        assert r.loop.forget("airpods") == {"ok": True}
        assert "airpods" not in r.loop.trackers
    finally:
        r.loop.stop()


def test_manual_enroll_still_works(tmp_path):
    seq, case = enroll_sequence()
    hands_by_ms = {int(ts * 1000): h for _, ts, h in seq}
    clf = FakeClassifier(sure("airpods"))
    r = Rig(tmp_path, items=ITEMS2, placed_on_tray=False, touch="real", classifier=clf,
            hands=FakeHands(fn=lambda f, ms: hands_by_ms.get(int(ms), [])))
    r.loop.start_enroll("wallet", "Wallet")
    for frame, ts, _ in seq:
        r.loop.tick(frame, ts)
    assert clf.calls == []
    assert set(r.loop.trackers) == {"wallet"} and r.loop.trackers["wallet"].state == "PLACED"
    assert Gallery.load("wallet", tmp_path / "gallery").meta["origin"] == "enrolled"
    assert [e["kind"] for e in r.store.recent_events(5)] == ["PLACED"]


# ---------------------------------------------------------------- gallery robustness
def test_corrupt_gallery_skips_only_that_item(tmp_path, caplog):
    save_gallery(tmp_path, "airpods")
    save_gallery(tmp_path, "glasses", box=DESK_CASE)
    (tmp_path / "gallery" / "airpods" / "pos.npy").write_bytes(b"not a numpy file")
    with caplog.at_level(logging.ERROR):
        r = Rig(tmp_path, items=("airpods", "glasses"))
    assert "airpods" not in r.loop.trackers and "glasses" in r.loop.trackers
    assert any("airpods" in m for m in caplog.messages)


def _held_airpods_rig(tmp_path, result, live_box=None):
    save_gallery(tmp_path)                               # airpods tracked, then held at (300, 100)
    clf = FakeClassifier(sure("glasses"))
    r = touch_rig(tmp_path, [[result]], classifier=clf, placed_on_tray=True)
    t = r.loop.trackers["airpods"]
    t.start_held((300, 100), T0 - DT)
    t.live_box = live_box
    return r, clf


def test_touch_inside_held_hand_box_does_not_lock(tmp_path):
    big_hand = (220, 40, 380, 180)                       # IoU with the small result box is < TRACKED_IOU
    r, clf = _held_airpods_rig(tmp_path, placed_result(at(300, 100, 20, 20)), live_box=big_hand)
    r.loop.tick(bg(), T0)
    assert clf.calls == [] and set(r.loop.trackers) == {"airpods"}
    assert r.store.recent_events(5) == []


def test_touch_near_held_hand_anchor_does_not_lock(tmp_path):
    r, clf = _held_airpods_rig(tmp_path, placed_result(at(380, 100)))   # 80 px from the anchor
    r.loop.tick(bg(), T0)
    assert clf.calls == [] and set(r.loop.trackers) == {"airpods"}


def test_touch_far_from_held_hand_still_locks(tmp_path):
    r, clf = _held_airpods_rig(tmp_path, placed_result(DESK_CASE))       # ~230 px from the anchor
    r.loop.tick(bg(), T0)
    assert len(clf.calls) == 1 and set(r.loop.trackers) == {"airpods", "glasses"}


def test_enroll_diagnostics_image_off_by_default(tmp_path):
    r = Rig(tmp_path, placed_on_tray=False)
    r.loop.start_enroll("wallet", "Wallet")
    r.loop.tick(bg(), T0)
    assert r.loop._session is not None and r.loop._session.debug_dir is None


def test_enroll_diagnostics_image_behind_flag(tmp_path):
    r = Rig(tmp_path, placed_on_tray=False)
    r.cfg.debug.enroll_diagnostics = True
    r.loop.start_enroll("wallet", "Wallet")
    r.loop.tick(bg(), T0)
    assert r.loop._session.debug_dir == r.clips


# ---------------------------------------------------------------- wearable mode
class WearRig:
    """Rig with camera.mode = wearable: no zones, a saved airpods gallery, nothing pre-placed."""

    def __init__(self, tmp_path, items=("airpods",), disabled=(), preplaced=False, hands=None, detector=None):
        self.cfg = make_cfg(tmp_path, items)
        self.cfg.camera.mode = "wearable"
        for it in self.cfg.items:
            it.enabled = it.id not in disabled
        self.bus = Bus()
        self.store = Store(str(tmp_path / "db.sqlite"), self.bus)
        if preplaced:
            self.store.upsert_item("airpods", "AirPods", False, "PLACED", "tray", TRAY_CASE, 0.9, T0 - 10)
        self.det = detector or FakeDetector()
        self.hands = hands or FakeHands()
        self.people, self.touch = FakePeople(), FakeTouch()
        self.clips = tmp_path / "clips"
        self.loop = VisionLoop(self.cfg, FakeCamera(), RingBuffer(), self.store, self.bus, ZoneMap([]),
                               self.det, self.hands, FakeEmbedder(), ChangeDetector(), self.clips,
                               people=self.people, classifier=FakeClassifier(), touch=self.touch)


def wear_sequence(n_hand=5, n_rest=6, n_gone=0, drift=0):
    """(frame, ts, hands, dets): hand on the case, case alone, then n_gone ticks without it.
    Each frame carries a tick-dependent corner patch so the camera never looks frozen."""
    seq, t = [], T0

    def add(case, hand):
        nonlocal t
        f = scene(case)                      # the hand is only in FakeHands: skin would change the crop
        paint(f, (0, 0, 60, 60), (len(seq) * 7) % 90)
        seq.append((f, t, [hand] if hand else [], [("airpods", case, 0.3)] if case else []))
        t += DT
    h = hand_at(440, 265)
    for _ in range(n_hand):
        add(TRAY_CASE, h)
    for i in range(n_rest):
        add((TRAY_CASE[0] + drift * i, TRAY_CASE[1], TRAY_CASE[2] + drift * i, TRAY_CASE[3]), None)
    for _ in range(n_gone):
        add(None, None)
    return seq


def wear_rig_for(tmp_path, seq, **kw):
    hands_by_ms = {int(ts * 1000): hands for _, ts, hands, _ in seq}
    dets = {}
    r = WearRig(tmp_path, hands=FakeHands(fn=lambda frame, ts_ms: hands_by_ms.get(int(ts_ms), [])),
                detector=FakeDetector(fn=lambda frame: dets["now"]), **kw)
    return r, dets


def test_wearable_touch_put_down_writes_placed(tmp_path):
    save_gallery(tmp_path)
    seq = wear_sequence()
    r, dets = wear_rig_for(tmp_path, seq)
    run(r, dets, seq)
    events = r.store.recent_events(10)[::-1]
    assert [e["kind"] for e in events] == ["PICKED_UP", "PLACED"]
    assert r.store.get_item("airpods")["state"] == "PLACED"
    assert r.loop.wear_status()[0][0].phase == "PLACED_VISIBLE"


def test_wearable_out_of_view_writes_seen_snapshot(tmp_path):
    save_gallery(tmp_path)
    seq = wear_sequence(n_rest=9, n_gone=10, drift=2)
    r, dets = wear_rig_for(tmp_path, seq)
    run(r, dets, seq)
    events = r.store.recent_events(10)[::-1]
    assert [e["kind"] for e in events] == ["PICKED_UP", "PLACED", "SEEN"]
    first_offer = seq[5 + PLACED_AT][3][0][1]   # the PLACED tick; equal scores keep the earliest
    last_seen = seq[5 + 8][3][0][1]
    assert tuple(events[-1]["bbox"]) == first_offer != last_seen   # best-frame path, not tracker.bbox
    assert Path(events[-1]["snapshot_path"]).exists()
    statuses, _ = r.loop.wear_status()
    assert statuses[0].phase == "PLACED_GONE" and statuses[0].item_id == "airpods"
    assert r.store.get_item("airpods")["state"] == "PLACED"
    assert r.loop.best["airpods"].best(seq[-1][1]) is None     # cleared after the SEEN


def test_wearable_starts_untracked(tmp_path):
    save_gallery(tmp_path)
    r = WearRig(tmp_path, preplaced=True)
    assert r.store.get_item("airpods")["state"] == "UNKNOWN"
    assert r.loop.wear_status()[0][0].phase == "UNTRACKED"
    assert r.store.recent_events(10) == []


def test_wearable_skips_change_and_people(tmp_path):
    save_gallery(tmp_path)
    seq = wear_sequence()[:5]
    r, dets = wear_rig_for(tmp_path, seq)
    run(r, dets, seq)
    assert r.people.calls == 0 and r.touch.enabled == []


def test_identical_frames_are_stale(tmp_path):
    save_gallery(tmp_path)
    r = WearRig(tmp_path)
    f = scene(TRAY_CASE)
    for i in range(12):
        r.loop.tick(f, T0 + i * DT)
    assert r.loop.wear_status()[1] is False and r.loop.metrics["camera_lost"] is True
    r.loop.tick(scene(DESK_CASE), T0 + 13 * DT)
    assert r.loop.wear_status()[1] is True and r.loop.metrics["camera_lost"] is False


def test_disabled_item_not_tracked(tmp_path):
    save_gallery(tmp_path)
    save_gallery(tmp_path, "keys", box=DESK_CASE)
    r = WearRig(tmp_path, items=("airpods", "keys"), disabled=("keys",))
    assert list(r.loop.trackers) == ["airpods"]
    assert r.store.get_item("keys") is not None


def test_seen_snapshot_shows_new_place_not_old(tmp_path):
    save_gallery(tmp_path)
    A, B, t, seq = DESK_CASE, TRAY_CASE, T0, []

    def add(case, hand):
        nonlocal t
        f = scene(case)
        paint(f, (0, 0, 60, 60), (len(seq) * 7) % 90)
        seq.append((f, t, [hand] if hand else [], [("airpods", case, 0.3)] if case else []))
        t += DT
    for _ in range(3):
        add(A, None)                          # seen hand-free at A before it is touched
    for _ in range(6):                        # (hand detection is throttled on odd idle ticks)
        add(A, hand_at(140, 265))
    for _ in range(8):
        add(B, None)                          # put down at B
    for _ in range(10):
        add(None, None)
    r, dets = wear_rig_for(tmp_path, seq)
    run(r, dets, seq)
    seen = [e for e in r.store.recent_events(10) if e["kind"] == "SEEN"]
    assert len(seen) == 1 and tuple(seen[0]["bbox"]) == B


def test_wearable_enroll_refused_and_loop_stays_healthy(tmp_path):
    save_gallery(tmp_path)
    r = WearRig(tmp_path)
    before = dict(r.loop.trackers)
    assert r.loop.click_enroll("x", "X", 10, 10)["ok"] is False
    assert r.loop.start_enroll("x", "X")["ok"] is False
    for i in range(3):
        r.loop.tick(paint(scene(TRAY_CASE), (0, 0, 40, 40), i * 50), T0 + i * DT)
    assert r.loop.trackers == before and r.loop._session is None
    assert r.loop.wear_status()[1] is True


def test_seen_long_after_last_sighting_uses_best_frame(tmp_path):
    save_gallery(tmp_path)
    seq = wear_sequence(n_rest=9, n_gone=10, drift=2)
    last_rest_ts = seq[5 + 8][1]
    seq = seq[:14] + [(f, last_rest_ts + (k + 1) * 0.8, h, d) for k, (f, _, h, d) in enumerate(seq[14:])]
    r, dets = wear_rig_for(tmp_path, seq)
    run(r, dets, seq)
    seen = [e for e in r.store.recent_events(10) if e["kind"] == "SEEN"]
    assert seen and seq[-1][1] - last_rest_ts > 5.0
    assert tuple(seen[0]["bbox"]) == seq[5 + PLACED_AT][3][0][1]   # best-frame box, not the fallback


def test_wearable_runs_detector_every_tick(tmp_path):
    save_gallery(tmp_path)
    r = WearRig(tmp_path)
    r.cfg.detector.every_n = 3
    for i in range(9):
        r.loop.tick(paint(scene(TRAY_CASE), (0, 0, 40, 40), i * 20), T0 + i * DT)
    assert r.det.calls == 9


def test_wearable_resets_untracked_config_rows(tmp_path):
    save_gallery(tmp_path)
    save_gallery(tmp_path, "keys", box=DESK_CASE)
    pre = Store(str(tmp_path / "db.sqlite"), Bus())
    pre.upsert_item("keys", "Keys", False, "PLACED", "desk", DESK_CASE, 0.9, T0 - 10)
    pre.upsert_item("wallet", "Wallet", False, "PLACED", "tray", TRAY_CASE, 0.9, T0 - 10)
    r = WearRig(tmp_path, items=("airpods", "keys", "wallet"), disabled=("keys",))
    assert list(r.loop.trackers) == ["airpods"]                 # wallet: enabled, no gallery
    assert r.store.get_item("keys")["state"] == "UNKNOWN"
    assert r.store.get_item("wallet")["state"] == "UNKNOWN"
