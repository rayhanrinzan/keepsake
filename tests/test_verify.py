"""CLIP second-opinion rule, with a stand-in scorer (the real model is checked on live frames)."""
import numpy as np

from conftest import obs
from verify import MIN_SCORE, PROMPTS, ClipVerifier


def verifier(scores: dict):
    """A ClipVerifier whose CLIP scores come from `scores[category]` = (item, best look-alike)."""
    v = ClipVerifier.__new__(ClipVerifier)
    v.available, v.reason, v._cache, v.calls = True, "", {}, 0

    def fake(frame, boxes):
        v.calls += 1
        return [scores[cat] for cat, _ in boxes]
    v.scores = fake
    return v


FRAME = np.zeros((360, 640, 3), np.uint8)


def test_lookalikes_are_dropped_and_real_items_kept():
    v = verifier({"wallet": (0.02, 0.9), "glasses": (0.98, 0.01), "car key": (0.6, 0.1)})
    shoe_as_wallet, glasses, keys = obs("wallet"), obs("glasses"), obs("car key")
    assert v.keep(FRAME, [shoe_as_wallet, glasses, keys]) == [glasses, keys]


def test_item_must_beat_its_lookalikes_and_reach_the_floor():
    assert verifier({"wallet": (0.4, 0.45)}).keep(FRAME, [obs("wallet")]) == []
    assert verifier({"wallet": (MIN_SCORE - 0.01, 0.1)}).keep(FRAME, [obs("wallet")]) == []
    assert len(verifier({"wallet": (MIN_SCORE + 0.01, 0.1)}).keep(FRAME, [obs("wallet")])) == 1


def test_people_and_hands_pass_through():
    v = verifier({})  # would fail if asked to score anything
    stuff = [obs("person", size=0.4), obs("hand")]
    assert v.keep(FRAME, stuff) == stuff


def test_bottle_and_backpack_are_checked_too():
    v = verifier({"bottle": (0.05, 0.8), "backpack": (0.9, 0.05)})
    shoe_as_bottle, backpack = obs("bottle"), obs("backpack")
    assert v.keep(FRAME, [shoe_as_bottle, backpack]) == [backpack]


def test_tiny_item_boxes_are_dropped_but_people_and_hands_are_not():
    from catalog import MIN_CONF
    from verify import MIN_ITEM_AREA, big_enough
    speck, keys = obs("bottle", size=0.03), obs("car key", size=0.1)
    person, hand = obs("person", size=0.03), obs("hand", size=0.03)
    assert 0.03 ** 2 < MIN_ITEM_AREA < 0.1 ** 2
    assert big_enough([speck, keys, person, hand], MIN_CONF) == [keys, person, hand]


def test_without_clip_everything_passes():
    v = verifier({})
    v.available = False
    wallet = obs("wallet")
    assert v.keep(FRAME, [wallet]) == [wallet]


def test_every_checked_item_is_in_the_catalog_with_lookalikes():
    from catalog import SUPPORTED
    assert set(PROMPTS) <= set(SUPPORTED)
    for pos, neg in PROMPTS.values():
        assert pos and len(neg) >= 5 and not set(pos) & set(neg)


def test_verdicts_are_cached_briefly_for_a_box_in_the_same_place():
    v = verifier({"wallet": (0.02, 0.9)})
    assert v.keep(FRAME, [obs("wallet")], now=0.0) == [] and v.calls == 1
    assert v.keep(FRAME, [obs("wallet")], now=0.5) == [] and v.calls == 1  # reused
    v.keep(FRAME, [obs("wallet", pos=(0.8, 0.8))], now=0.6)  # moved: checked again
    v.keep(FRAME, [obs("wallet")], now=2.0)  # expired: checked again
    assert v.calls == 3
