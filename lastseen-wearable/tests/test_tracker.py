"""ItemTracker state machine: hand-led pick-up / put-down, honest HIDDEN / CARRIED_OUT. No models."""
import itertools

import pytest

from lastseen.config import EngineCfg, IdentityCfg
from lastseen.engine.tracker import ItemTracker
from lastseen.engine.zones import Zone, ZoneMap
from lastseen.types import Candidate, Person, TickObs

WH = (1280, 720)
_clock = itertools.count()


def rect(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


# tray px x 704-960 y 396-612; desk px x 128-512 y 360-648; bed px x 576-1152 y 36-324
ZONES = ZoneMap([
    Zone("tray", "surface", rect(0.55, 0.55, 0.75, 0.85)),
    Zone("desk", "surface", rect(0.10, 0.50, 0.40, 0.90)),
    Zone("bed", "cover", rect(0.45, 0.05, 0.90, 0.45)),
])

TRAY_BOX = (800, 480, 860, 540)
TRAY_XY = (830, 510)
DESK_BOX = (300, 500, 360, 560)
DESK_XY = (330, 530)
BED_BOX = (830, 150, 890, 210)
BED_XY = (860, 180)
NOWHERE_XY = (600, 360)    # in no zone, far from the edges
EDGE_XY = (20, 360)        # within 5% of the left edge
FAR_BOX = (100, 100, 160, 160)


# ---------------------------------------------------------------- builders
def center(b):
    return ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)


def hand_at(x, y, size=60):
    h = size // 2
    return (int(x - h), int(y - h), int(x + h), int(y + h))


def cand(box, sim=0.9, margin=0.12, source="det"):
    return Candidate(box=tuple(box), sim=sim, margin=margin, source=source)


def person_at(track_id, x, y):
    return Person(track_id=track_id, box=(int(x - 100), int(y - 250), int(x + 100), int(y + 250)),
                  feet=(int(x), int(y + 250)))


def obs(hands=(), cands=(), change=(), persons=(), left_view=(), ts=None):
    return TickObs(ts=next(_clock) * 0.125 if ts is None else ts, frame_wh=WH, hands=list(hands),
                   candidates=list(cands), change_boxes=list(change), persons=list(persons),
                   left_view=list(left_view))


def stored(sim, margin=0.12, box=TRAY_BOX):
    return cand(box, sim=sim, margin=margin, source="stored")


STORED_OK = stored(0.9)
STORED_FAIL = stored(0.3, margin=-0.1)


def _persons(person, xy):
    return [person_at(person, *xy)] if person is not None else []


def pickup_seq(person=None, hand_last_in=None):
    """Hand rests on the tray item for held_frames ticks (still verified), then the hand lifts off the
    spot and the item is gone from it: PICKED_UP."""
    seq = [obs(hands=[hand_at(*TRAY_XY)], cands=[STORED_OK], persons=_persons(person, TRAY_XY))
           for _ in range(3)]
    lifted = (TRAY_XY[0], TRAY_XY[1] - 90)  # off the tray box
    seq.append(obs(hands=[hand_at(*lifted)], cands=[STORED_FAIL], persons=_persons(person, lifted)))
    if hand_last_in is not None:
        seq.append(obs(hands=[hand_at(*hand_last_in)], persons=_persons(person, hand_last_in)))
    return seq


def held_obs(person=None, left_view=(), at=TRAY_XY):
    return obs(hands=[hand_at(*at)], persons=_persons(person, at), left_view=left_view)


def carry_seq(to, start=TRAY_XY, steps=5):
    out = []
    for i in range(1, steps + 1):
        f = i / steps
        out.append(held_obs(at=(start[0] + (to[0] - start[0]) * f, start[1] + (to[1] - start[1]) * f)))
    return out


def putdown_seq(box, sim=0.9, margin=0.12, change=(), n=6):
    """Item sits still at `box`; the releasing hand hovers 90 px to the side (no overlap)."""
    cx, cy = center(box)
    return [obs(hands=[hand_at(cx + 90, cy)], cands=[cand(box, sim, margin)], change=change)
            for _ in range(n)]


def run(tracker, obs_list):
    evs = []
    for o in obs_list:
        evs.extend(tracker.step(o))
    return evs


def kinds(evs):
    return [e.kind for e in evs]


def make_tracker():
    return ItemTracker("keys", EngineCfg(), IdentityCfg(), ZONES)


@pytest.fixture
def t():
    tr = make_tracker()
    tr.restore({"state": "PLACED", "zone": "tray", "bbox": list(TRAY_BOX),
                "confidence": 0.9, "last_seen_ts": 100.0})
    return tr


t_placed_on_tray = t


# ---------------------------------------------------------------- brief tests
def test_pickup_then_putdown(t_placed_on_tray):  # A2
    t = t_placed_on_tray
    evs = run(t, pickup_seq() + carry_seq(to=DESK_XY) + putdown_seq(DESK_BOX))
    assert kinds(evs) == ["PICKED_UP", "PLACED"]
    assert evs[0].from_zone == "tray" and evs[0].bbox == TRAY_BOX and evs[0].confidence == 0.9
    assert evs[1].from_zone == "tray" and evs[1].to_zone == "desk" and evs[1].bbox == DESK_BOX
    assert evs[1].confidence == pytest.approx(0.72)
    assert t.state == "PLACED" and t.zone == "desk" and t.bbox == DESK_BOX
    assert t.last_placed_ts == evs[1].ts and t.confidence == pytest.approx(0.72)
    assert t.live_box is None


def test_no_location_while_held(t):  # A3
    run(t, pickup_seq() + [held_obs() for _ in range(30)])
    assert t.state == "HELD" and t.zone == "tray" and t.bbox == TRAY_BOX
    assert t.live_box == hand_at(*TRAY_XY)


def test_hand_brush_is_not_pickup(t):
    evs = run(t, [obs(hands=[hand_at(*TRAY_XY)], cands=[STORED_OK]) for _ in range(10)])
    assert evs == [] and t.state == "PLACED"


def test_occlusion_keeps_placed(t):  # A5
    evs = run(t, [obs(cands=[STORED_FAIL]) for _ in range(40)])
    assert evs == [] and t.state == "PLACED" and t.zone == "tray"


def test_far_lookalike_ignored_on_putdown(t):  # A4
    evs = run(t, pickup_seq() + [obs(cands=[cand(FAR_BOX, sim=0.85, margin=0.08)]) for _ in range(10)])
    assert "PLACED" not in kinds(evs)


def test_far_strong_match_is_accepted_on_putdown(t):
    evs = run(t, pickup_seq() + [obs(hands=[hand_at(*TRAY_XY)],
                                     cands=[cand(FAR_BOX, sim=0.85, margin=0.16)]) for _ in range(6)])
    assert kinds(evs) == ["PICKED_UP", "PLACED"]


def test_weak_putdown_is_uncertain(t):
    evs = run(t, pickup_seq() + carry_seq(to=DESK_XY) + putdown_seq(DESK_BOX, sim=0.81, margin=0.04))
    assert kinds(evs) == ["PICKED_UP", "PLACED"]
    # 0.4*0.55 + 0.4*0.267 + 0.2*0
    assert evs[-1].confidence == pytest.approx(0.3267, abs=1e-3)
    assert evs[-1].confidence < EngineCfg().uncertain_conf


def test_change_support_raises_confidence(t):
    evs = run(t, pickup_seq() + carry_seq(to=DESK_XY)
              + putdown_seq(DESK_BOX, change=[(298, 498, 362, 562)]))
    assert evs[-1].confidence == pytest.approx(0.92)


def test_held_timeout_in_cover_is_hidden(t):
    evs = run(t, pickup_seq(hand_last_in=BED_XY) + [obs() for _ in range(10)])
    assert kinds(evs) == ["PICKED_UP", "HIDDEN"]
    assert evs[-1].to_zone == "bed" and evs[-1].confidence == 0.5
    assert evs[-1].bbox == hand_at(*BED_XY)
    assert t.state == "HIDDEN" and t.zone == "bed"


def test_held_timeout_needs_full_missing_frames(t):
    evs = run(t, pickup_seq(hand_last_in=BED_XY) + [obs() for _ in range(9)])
    assert kinds(evs) == ["PICKED_UP"] and t.state == "HELD"


def test_held_timeout_nowhere_is_unknown_keeps_last_place(t):
    evs = run(t, pickup_seq(hand_last_in=NOWHERE_XY) + [obs() for _ in range(10)])
    assert kinds(evs) == ["PICKED_UP"]
    assert t.state == "UNKNOWN" and t.zone == "tray" and t.bbox == TRAY_BOX
    assert t.last_placed_ts == 100.0


def test_held_timeout_near_edge_is_carried_out(t):
    evs = run(t, pickup_seq(hand_last_in=EDGE_XY) + [obs() for _ in range(10)])
    assert kinds(evs) == ["PICKED_UP", "CARRIED_OUT"]
    assert evs[-1].to_zone is None and evs[-1].confidence == 0.5
    assert t.state == "CARRIED_OUT"


def test_carried_out_when_holder_leaves_view(t):  # A11
    evs = run(t, pickup_seq(person=7) + [held_obs(person=7, left_view=[7])])
    assert kinds(evs) == ["PICKED_UP", "CARRIED_OUT"]
    assert evs[-1].to_zone is None and evs[-1].confidence == 0.9
    assert evs[-1].bbox == hand_at(*TRAY_XY)
    assert t.state == "CARRIED_OUT" and t.holder_track_id is None


def test_holder_leaving_after_disappearing_from_persons(t):
    evs = run(t, pickup_seq(person=7) + [obs(left_view=[7])])
    assert kinds(evs) == ["PICKED_UP", "CARRIED_OUT"]


def test_holder_is_nearest_person_when_none_contains_hand(t):
    far7 = person_at(7, 1000, 300)       # box x 900-1100: does not contain the tray hand (830)
    far9 = person_at(9, 200, 300)
    seq = pickup_seq() + [obs(hands=[hand_at(*TRAY_XY)], persons=[far7, far9])]
    run(t, seq)
    assert t.holder_track_id == 7


def test_other_person_leaving_ignored(t):
    evs = run(t, pickup_seq(person=7) + [held_obs(person=7, left_view=[9]) for _ in range(3)])
    assert kinds(evs) == ["PICKED_UP"]


def test_restore_from_row():
    t = make_tracker()
    t.restore({"state": "PLACED", "zone": "desk", "bbox": "[1,2,3,4]", "confidence": 0.8,
               "last_seen_ts": 5.0})
    assert t.bbox == (1, 2, 3, 4) and t.state == "PLACED" and t.zone == "desk"
    assert t.confidence == 0.8 and t.last_placed_ts == 5.0


# ---------------------------------------------------------------- extra coverage
def test_initial_state_unknown():
    t = make_tracker()
    assert t.state == "UNKNOWN" and t.bbox is None and t.zone is None and t.hand_anchor() is None


def test_restore_with_bbox_list_and_missing_state():
    t = make_tracker()
    t.restore({"zone": None, "bbox": [10, 20, 30, 40]})
    assert t.state == "UNKNOWN" and t.bbox == (10, 20, 30, 40)
    t.restore({"state": "HIDDEN", "zone": "bed", "bbox": None})
    assert t.state == "HIDDEN" and t.bbox is None


def test_arm_then_brush_disarm_by_verification(t):
    hand_on = [obs(hands=[hand_at(*TRAY_XY)], cands=[STORED_OK]) for _ in range(4)]   # armed
    hand_off = [obs(cands=[STORED_OK]) for _ in range(3)]                             # disarm
    occluded = [obs(cands=[STORED_FAIL]) for _ in range(5)]
    evs = run(t, hand_on + hand_off + occluded)
    assert evs == [] and t.state == "PLACED"


def test_arm_then_disarm_when_hand_gone(t):
    hand_on = [obs(hands=[hand_at(*TRAY_XY)]) for _ in range(3)]
    gone = [obs() for _ in range(10)]
    evs = run(t, hand_on + gone + [obs(cands=[STORED_FAIL])])
    assert evs == [] and t.state == "PLACED"


def test_armed_failure_shortly_after_hand_leaves_is_pickup(t):
    hand_on = [obs(hands=[hand_at(*TRAY_XY)], cands=[STORED_OK]) for _ in range(3)]
    evs = run(t, hand_on + [obs(), obs(cands=[STORED_FAIL])])
    assert kinds(evs) == ["PICKED_UP"]
    assert t.hand_anchor() == (830, 510)


def test_armed_far_candidate_is_pickup(t):
    hand_on = [obs(hands=[hand_at(*TRAY_XY)]) for _ in range(3)]
    moved = obs(hands=[hand_at(*TRAY_XY)], cands=[cand((870, 480, 930, 540))])  # 70 px away
    evs = run(t, hand_on + [moved])
    assert kinds(evs) == ["PICKED_UP"] and evs[0].from_zone == "tray"


def test_hand_overlap_too_short_does_not_arm(t):
    seq = [obs(hands=[hand_at(*TRAY_XY)]) for _ in range(2)] + [obs(cands=[STORED_FAIL])]
    assert run(t, seq) == []


def test_placed_moved_without_hand(t):
    evs = run(t, [obs(cands=[cand(DESK_BOX)]) for _ in range(6)])
    assert kinds(evs) == ["PLACED"]
    assert evs[0].from_zone == "tray" and evs[0].to_zone == "desk"
    assert t.zone == "desk" and t.bbox == DESK_BOX


def test_placed_small_shift_is_not_a_move(t):
    evs = run(t, [obs(cands=[cand((810, 480, 870, 540))]) for _ in range(10)])  # 10 px
    assert evs == []


def test_reacquire_from_unknown_is_placed():
    t = make_tracker()
    evs = run(t, [obs(cands=[cand(DESK_BOX)]) for _ in range(6)])
    assert kinds(evs) == ["PLACED"] and evs[0].to_zone == "desk"
    assert t.state == "PLACED" and t.zone == "desk"


def test_reacquire_uses_stricter_thresholds():
    t = make_tracker()
    # accepted when following (>= 0.70 / 0.02) but not when reacquiring (>= 0.75 / 0.04)
    evs = run(t, [obs(cands=[cand(DESK_BOX, sim=0.73, margin=0.03)]) for _ in range(10)])
    assert evs == [] and t.state == "UNKNOWN"


def test_reacquire_from_hidden_same_zone_is_seen():
    t = make_tracker()
    t.restore({"state": "HIDDEN", "zone": "bed", "bbox": list(TRAY_BOX)})
    evs = run(t, [obs(cands=[cand(BED_BOX)]) for _ in range(6)])
    assert kinds(evs) == ["SEEN"]
    assert evs[0].from_zone == "bed" and evs[0].to_zone == "bed"
    assert t.state == "PLACED" and t.bbox == BED_BOX


def test_hidden_then_found_in_same_cover_is_seen(t):
    run(t, pickup_seq(hand_last_in=BED_XY) + [obs() for _ in range(10)])
    evs = run(t, [obs(cands=[cand(BED_BOX)]) for _ in range(6)])
    assert kinds(evs) == ["SEEN"]


def test_putdown_candidate_overlapping_hand_is_ignored(t):
    in_hand = [obs(hands=[hand_at(*DESK_XY)], cands=[cand(DESK_BOX)]) for _ in range(10)]
    evs = run(t, pickup_seq() + carry_seq(to=DESK_XY) + in_hand)
    assert kinds(evs) == ["PICKED_UP"] and t.state == "HELD" and t.zone == "tray"


def test_stillness_resets_when_candidate_jumps(t):
    run(t, pickup_seq() + carry_seq(to=DESK_XY))
    jumpy = []
    for i in range(8):
        dx = 10 * (i % 2)   # alternates 10 px > still_px
        box = (DESK_BOX[0] + dx, DESK_BOX[1], DESK_BOX[2] + dx, DESK_BOX[3])
        jumpy.append(obs(cands=[cand(box)]))
    assert run(t, jumpy) == [] and t.state == "HELD"
    assert kinds(run(t, putdown_seq(DESK_BOX))) == ["PLACED"]


def test_stillness_resets_on_gap_tick(t):
    run(t, pickup_seq() + carry_seq(to=DESK_XY))
    seq = putdown_seq(DESK_BOX, n=5) + [held_obs(at=(DESK_XY[0] + 90, DESK_XY[1]))] + putdown_seq(DESK_BOX, n=5)
    assert run(t, seq) == [] and t.state == "HELD"


def test_live_box_follows_hand_nearest_anchor(t):
    run(t, pickup_seq())
    other = hand_at(100, 600)
    run(t, [obs(hands=[other, hand_at(850, 520)])])
    assert t.live_box == hand_at(850, 520) and t.hand_anchor() == (850, 520)
    run(t, [obs()])
    assert t.hand_anchor() == (850, 520)


@pytest.mark.parametrize("state,expected", [
    ("UNKNOWN", True), ("HIDDEN", True), ("CARRIED_OUT", True), ("PLACED", False), ("HELD", False),
])
def test_needs_global_search(state, expected):
    t = make_tracker()
    t.restore({"state": state, "zone": "tray", "bbox": list(TRAY_BOX)})
    assert t.needs_global_search() is expected


def test_needs_global_search_after_live_pickup(t):
    run(t, pickup_seq())
    assert t.state == "HELD" and t.needs_global_search() is False


# ---------------------------------------------------------------- fix round 1
def test_putdown_counts_when_hand_moves_far_away_after_release(t):
    """R9.4/R9.6 correction: proximity uses the holding hand's anchor history (last 2.0 s)."""
    run(t, pickup_seq() + carry_seq(to=DESK_XY))
    away = (DESK_XY[0] + 400, DESK_XY[1])      # > near_hand_px from the desk item
    seq = [obs(hands=[hand_at(DESK_XY[0] + 90, DESK_XY[1])], cands=[cand(DESK_BOX, 0.85, 0.08)])]
    seq += [obs(hands=[hand_at(*away)], cands=[cand(DESK_BOX, 0.85, 0.08)]) for _ in range(5)]
    evs = run(t, seq)
    assert kinds(evs) == ["PLACED"] and evs[0].to_zone == "desk"
    assert t.hand_anchor() is None and t.state == "PLACED"


def test_hand_anchor_is_live_not_history(t):
    run(t, pickup_seq() + carry_seq(to=DESK_XY))
    run(t, [held_obs(at=(900, 200))])
    assert t.hand_anchor() == (900, 200)


def test_anchor_older_than_two_seconds_no_longer_counts(t):
    run(t, pickup_seq() + carry_seq(to=DESK_XY))
    away = (DESK_XY[0] + 400, DESK_XY[1])
    run(t, [held_obs(at=away) for _ in range(17)])          # 17 * 0.125 s = 2.125 s > 2.0 s
    evs = run(t, [obs(hands=[hand_at(*away)], cands=[cand(DESK_BOX, 0.85, 0.08)]) for _ in range(8)])
    assert evs == [] and t.state == "HELD"


def test_anchor_history_cleared_on_transition(t):
    run(t, pickup_seq() + carry_seq(to=DESK_XY) + putdown_seq(DESK_BOX))
    assert t.state == "PLACED" and len(t._anchor_hist) == 0


@pytest.mark.parametrize("lookalike", [
    (870, 480, 930, 540),    # 70 px from bbox: >= move_px, within near_hand_px of the hand
    (100, 100, 160, 160),    # far beyond near_hand_px
])
def test_armed_brush_with_verified_stored_and_lookalike_is_not_pickup(t, lookalike):
    hand_on = [obs(hands=[hand_at(*TRAY_XY)], cands=[STORED_OK]) for _ in range(3)]
    brush = [obs(hands=[hand_at(*TRAY_XY)], cands=[STORED_OK, cand(lookalike)]) for _ in range(5)]
    evs = run(t, hand_on + brush)
    assert evs == [] and t.state == "PLACED" and t.bbox == TRAY_BOX


def test_armed_far_lookalike_without_stored_is_not_pickup(t):
    """R9.3a(b): the moved-away candidate must be within near_hand_px of the overlapping hand."""
    hand_on = [obs(hands=[hand_at(*TRAY_XY)]) for _ in range(3)]
    evs = run(t, hand_on + [obs(hands=[hand_at(*TRAY_XY)], cands=[cand(FAR_BOX)]) for _ in range(3)])
    assert evs == [] and t.state == "PLACED"


def test_start_held_at_anchor_then_putdown_nearby():
    t = make_tracker()
    t.restore({"state": "PLACED", "zone": "desk", "bbox": list(DESK_BOX), "confidence": 0.9,
               "last_seen_ts": 5.0})
    t.start_held(DESK_XY, 6.0)
    assert t.state == "HELD" and t.hand_anchor() == DESK_XY and t.live_box is None
    assert t.bbox == DESK_BOX and t.zone == "desk"          # last placed spot kept
    evs = run(t, [obs(ts=6.1 + 0.1 * i, cands=[cand(TRAY_BOX)]) for i in range(6)])
    assert kinds(evs) == []                                  # TRAY_BOX is far from the anchor
    evs = run(t, putdown_seq((310, 510, 370, 570)))
    assert kinds(evs) == ["PLACED"] and t.state == "PLACED"


# ---------------------------------------------------------------- resting hand (no phantom pick-up)
LIFTED_XY = (TRAY_XY[0], TRAY_XY[1] - 90)   # hand raised off the tray box: no overlap


def test_hand_resting_on_item_occluding_it_is_not_pickup(t):
    resting = [obs(hands=[hand_at(*TRAY_XY)], cands=[STORED_FAIL]) for _ in range(10)]
    leaves = [obs(cands=[STORED_OK]) for _ in range(5)]
    evs = run(t, resting + leaves)
    assert evs == [] and t.state == "PLACED" and t.zone == "tray" and t.bbox == TRAY_BOX


def test_real_lift_is_pickup_once_hand_leaves_the_spot(t):
    on = [obs(hands=[hand_at(*TRAY_XY)], cands=[STORED_OK]) for _ in range(3)]
    lifting = [obs(hands=[hand_at(*TRAY_XY)], cands=[STORED_FAIL]) for _ in range(4)]
    assert run(t, on + lifting) == [] and t.state == "PLACED"
    evs = run(t, [obs(hands=[hand_at(*LIFTED_XY)], cands=[STORED_FAIL])])
    assert kinds(evs) == ["PICKED_UP"] and evs[0].from_zone == "tray" and t.state == "HELD"
