import numpy as np

from lastseen.config import EngineCfg, WearableCfg
from lastseen.engine.wear_tracker import BestFrame, WearObs, WearTracker, frame_score
from lastseen.types import Candidate

B = (100, 100, 160, 160)
HAND = (90, 90, 170, 170)
WH = (640, 480)
STEP = 0.125


class Clock:
    def __init__(self):
        self.t = 1000.0

    def tick(self):
        self.t += STEP
        return self.t


def obs(ts, seen=True, hand=False, looked=True, fresh=True, box=B):
    cand = Candidate(box=box, sim=0.9, margin=0.2, source="det") if seen else None
    return WearObs(ts=ts, looked=looked, fresh=fresh, hands=[HAND] if hand else [], cand=cand,
                   accepted=seen, frame_wh=WH)


def mk():
    return WearTracker("keys", EngineCfg(), WearableCfg()), Clock()


def run(tr, clk, n, **kw):
    ev = []
    for _ in range(n):
        ev += tr.step(obs(clk.tick(), **kw))
    return ev


def to_visible(tr, clk):
    ev = run(tr, clk, 5, hand=True)
    ev += run(tr, clk, 6)
    return ev


def to_gone(tr, clk):
    to_visible(tr, clk)
    return run(tr, clk, 10, seen=False)


def test_touch_then_release_tracks():
    tr, clk = mk()
    ev = run(tr, clk, 5, hand=True)
    assert [e.kind for e in ev] == ["PICKED_UP"]
    assert ev[0].from_zone is None and ev[0].bbox == B
    assert tr.phase == "HELD" and tr.state == "HELD"
    ev = run(tr, clk, 6)
    assert [e.kind for e in ev] == ["PLACED"]
    assert ev[0].to_zone is None and ev[0].bbox == B
    assert tr.phase == "PLACED_VISIBLE" and tr.state == "PLACED"
    assert tr.last_placed_ts is not None and tr.zone is None


def test_brief_touch_does_not_track():
    tr, clk = mk()
    ev = run(tr, clk, 2, hand=True)
    ev += run(tr, clk, 10)
    assert ev == [] and tr.phase == "UNTRACKED" and tr.state == "UNKNOWN"


def test_seen_but_never_touched_stays_untracked():
    tr, clk = mk()
    assert run(tr, clk, 40) == []


def test_held_out_of_view_is_with_you():
    tr, clk = mk()
    run(tr, clk, 5, hand=True)
    ev = run(tr, clk, 10, seen=False)
    assert [e.kind for e in ev] == ["CARRIED_OUT"]
    assert tr.phase == "WITH_YOU" and tr.state == "CARRIED_OUT" and tr.unseen_s == 0


def test_placed_then_gone_emits_seen_and_counts():
    tr, clk = mk()
    to_visible(tr, clk)
    ev = run(tr, clk, 10, seen=False)
    assert [e.kind for e in ev] == ["SEEN"] and ev[0].bbox == B
    assert tr.phase == "PLACED_GONE" and abs(tr.unseen_s - 10 * STEP) < 1e-9   # timer starts at last sighting
    run(tr, clk, 230, seen=False)
    assert abs(tr.unseen_s - 30.0) < 0.01


def test_gone_timer_from_last_sighting_is_clamped():
    tr, clk = mk()
    to_visible(tr, clk)
    run(tr, clk, 9, seen=False)
    ev = tr.step(obs(clk.t + 60.0, seen=False))       # long stall before the 10th missing tick
    assert [e.kind for e in ev] == ["SEEN"]
    assert tr.unseen_s <= EngineCfg().missing_frames * WearableCfg().stale_frame_s
    assert tr.unseen_s > 0


def test_not_looked_ticks_do_not_count_missing():
    tr, clk = mk()
    to_visible(tr, clk)
    for i in range(18):
        tr.step(obs(clk.tick(), seen=False, looked=(i % 2 == 0)))
    assert tr.phase == "PLACED_VISIBLE"


def test_seen_again_needs_three_hits_in_window():
    tr, clk = mk()
    to_gone(tr, clk)
    run(tr, clk, 8, seen=False)
    before = tr.unseen_s
    assert before > 0
    run(tr, clk, 1)
    assert tr.phase == "PLACED_GONE" and tr.unseen_s >= before
    ev = run(tr, clk, 2)
    assert ev == [] and tr.phase == "PLACED_VISIBLE"
    assert tr.sightings == 1 and tr.unseen_s == 0


def test_stale_ticks_do_not_advance_timer():
    tr, clk = mk()
    to_gone(tr, clk)
    run(tr, clk, 8, seen=False)
    u = tr.unseen_s
    run(tr, clk, 20, seen=False, fresh=False)
    assert tr.unseen_s == u


def test_gap_is_clamped():
    tr, clk = mk()
    to_gone(tr, clk)
    u = tr.unseen_s
    tr.step(obs(clk.t + 10.0, seen=False))
    assert abs(tr.unseen_s - (u + 1.0)) < 1e-9


def test_with_you_put_down_out_of_view():
    tr, clk = mk()
    run(tr, clk, 5, hand=True)
    run(tr, clk, 10, seen=False)
    ev = run(tr, clk, 3)
    assert [e.kind for e in ev] == ["PLACED"]
    assert tr.phase == "PLACED_VISIBLE" and tr.sightings == 1 and tr.state == "PLACED"


def test_frame_score_prefers_big_central_sharp():
    central = frame_score(0.9, 200, (290, 210, 350, 270), WH)
    edge = frame_score(0.9, 200, (0, 210, 60, 270), WH)
    tiny = frame_score(0.9, 200, (300, 220, 306, 226), WH)
    assert central > edge > tiny


def test_best_frame_window():
    bf = BestFrame(5.0)
    scores = [0.1, 0.9, 0.3, 0.2, 0.6, 0.4, 0.5, 0.35]
    for t, s in enumerate(scores):
        bf.offer(float(t), s, np.full((2, 2, 3), t, dtype=np.uint8), B)
    frame, box, score = bf.best(7.0)
    assert score == 0.6 and box == B and frame[0, 0, 0] == 4
    bf.clear()
    assert bf.best(7.0) is None


def test_live_box_survives_not_looked_ticks():
    tr, clk = mk()
    tr.step(obs(clk.tick()))
    assert tr.live_box == B
    tr.step(obs(clk.tick(), seen=False, looked=False))
    assert tr.live_box == B                      # detector did not run: keep the overlay box
    tr.step(obs(clk.tick(), seen=False))
    assert tr.live_box is None                   # looked and not seen: cleared


def test_flickery_release_still_counts_as_put_down():
    # neck camera: after letting go the item is matched only now and then before the wearer looks away
    tr, clk = mk()
    run(tr, clk, 5, hand=True)
    ev = []
    for seen in (True, False, False, True, False, True):
        ev += tr.step(obs(clk.tick(), seen=seen))
    assert [e.kind for e in ev] == ["PLACED"] and tr.phase == "PLACED_VISIBLE"
    ev = run(tr, clk, 10, seen=False)
    assert [e.kind for e in ev] == ["SEEN"] and tr.phase == "PLACED_GONE"


def test_hand_sighting_resets_put_down_count():
    tr, clk = mk()
    run(tr, clk, 5, hand=True)
    run(tr, clk, 2)
    run(tr, clk, 1, hand=True)
    ev = run(tr, clk, 2)
    assert ev == [] and tr.phase == "HELD"


def test_too_few_free_sightings_then_gone_is_with_you():
    tr, clk = mk()
    run(tr, clk, 5, hand=True)
    run(tr, clk, 2)
    ev = run(tr, clk, 10, seen=False)
    assert [e.kind for e in ev] == ["CARRIED_OUT"] and tr.phase == "WITH_YOU"
