import numpy as np
import pytest

from lastseen.vision.change import ChangeDetector
from lastseen.vision.geometry import iou
from tests.fakes import FakeHands

H, W = 180, 320
CASE_BOX = (200, 100, 212, 110)
HAND_BOX = (150, 60, 190, 100)


def make_bg():
    return np.full((H, W, 3), 100, np.uint8)


def with_case(bg, x=200, y=100):
    f = bg.copy()
    f[y:y + 10, x:x + 12] = 255
    return f


def with_hand(bg):
    f = bg.copy()
    x1, y1, x2, y2 = HAND_BOX
    f[y1:y2, x1:x2] = (90, 140, 200)
    return f


def warmed(cd, bg, n=5, t0=0.0):
    for i in range(n):
        cd.update(bg, [], ts=t0 + i * 0.5)
    return t0 + n * 0.5


def test_appeared_object_found_near_hand():
    bg = make_bg()
    cd = ChangeDetector()
    cd.update(bg, [], ts=0.0)
    r = cd.snapshot()
    out = cd.blobs(r, with_case(bg), near=(205, 105), radius=60)
    assert out and iou(out[0], CASE_BOX) > 0.5


def test_hand_pixels_not_learned():
    bg = make_bg()
    cd = ChangeDetector()
    cd.update(bg, [], ts=0.0)
    hand_frame = with_hand(bg)
    for i in range(30):
        cd.update(hand_frame, [HAND_BOX], ts=1.0 + i * 0.5)
    assert cd.blobs(None, bg) == []


def test_no_learning_within_one_second_of_hand():
    bg = make_bg()
    cd = ChangeDetector()
    cd.update(bg, [], ts=0.0)
    cd.update(bg, [HAND_BOX], ts=10.0)
    scene = with_case(bg)
    for i in range(30):  # < 1s after hand: must not absorb the case
        cd.update(scene, [], ts=10.0 + 0.02 * i)
    assert cd.blobs(None, scene)  # case still reads as change
    for i in range(200):  # long after: gets absorbed
        cd.update(scene, [], ts=12.0 + 0.5 * i)
    assert cd.blobs(None, scene) == []


def test_lighting_noise_ignored():
    bg = make_bg()
    cd = ChangeDetector()
    cd.update(bg, [], ts=0.0)
    r = cd.snapshot()
    assert cd.blobs(r, np.clip(bg.astype(int) + 3, 0, 255).astype(np.uint8)) == []


def test_huge_change_ignored():
    bg = make_bg()
    cd = ChangeDetector()
    cd.update(bg, [], ts=0.0)
    r = cd.snapshot()
    assert cd.blobs(r, np.full_like(bg, 255)) == []


def test_near_filter_excludes_far_blob():
    bg = make_bg()
    cd = ChangeDetector()
    cd.update(bg, [], ts=0.0)
    r = cd.snapshot()
    f = with_case(bg, 200, 100)
    f[20:30, 20:32] = 255  # second blob far away
    both = cd.blobs(r, f)
    assert len(both) == 2
    near = cd.blobs(r, f, near=(205, 105), radius=60)
    assert len(near) == 1 and iou(near[0], CASE_BOX) > 0.5
    ordered = cd.blobs(r, f, near=(26, 25), radius=400)
    assert ordered[0][0] < 100  # sorted by distance to near


def test_snapshot_is_frozen():
    bg = make_bg()
    cd = ChangeDetector()
    cd.update(bg, [], ts=0.0)
    r = cd.snapshot()
    scene = with_case(bg)
    for i in range(200):
        cd.update(scene, [], ts=5.0 + i * 0.5)
    assert cd.blobs(None, scene) == []
    assert cd.blobs(r, scene)


def test_drop_removes_reference():
    cd = ChangeDetector()
    cd.update(make_bg(), [], ts=0.0)
    r = cd.snapshot()
    cd.drop(r)
    with pytest.raises(KeyError):
        cd.blobs(r, make_bg())
    cd.drop(r)  # dropping twice is a no-op


def test_boxes_mapped_to_full_frame_when_downscaled():
    bg = np.full((360, 640, 3), 100, np.uint8)
    cd = ChangeDetector(work_width=320)
    cd.update(bg, [], ts=0.0)
    r = cd.snapshot()
    f = bg.copy()
    f[200:230, 400:440] = 255
    out = cd.blobs(r, f)
    assert out and iou(out[0], (400, 200, 440, 230)) > 0.6


def test_fake_hands_script():
    fh = FakeHands([[(1, 2, 3, 4)], []], raise_on=2)
    assert fh.detect(None, 0) == [(1, 2, 3, 4)]
    assert fh.detect(None, 1) == []
    with pytest.raises(RuntimeError):
        fh.detect(None, 2)
    assert fh.detect(None, 3) == []
