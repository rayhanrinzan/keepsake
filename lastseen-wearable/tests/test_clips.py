import os

import cv2
import numpy as np

from lastseen.memory.clips import cleanup_old, write_clip, write_snapshot


def test_snapshot_written(tmp_path):
    out = tmp_path / "sub"
    p = write_snapshot(np.zeros((360, 640, 3), np.uint8), (100, 100, 140, 140), "desk", out)
    assert p.exists() and p.name.startswith("snap_") and p.suffix == ".jpg"
    assert cv2.imread(str(p)) is not None


def test_snapshot_does_not_mutate_input(tmp_path):
    frame = np.full((360, 640, 3), 180, np.uint8)
    before = frame.copy()
    write_snapshot(frame, (100, 100, 140, 140), "desk", tmp_path)
    assert np.array_equal(frame, before)


def test_snapshot_unique_names_and_edge_box(tmp_path):
    f = np.zeros((100, 100, 3), np.uint8)
    a = write_snapshot(f, (0, 0, 10, 10), "x", tmp_path)
    b = write_snapshot(f, (90, 90, 100, 100), "x", tmp_path)
    assert a != b and a.exists() and b.exists()


def test_clip_empty_returns_none(tmp_path):
    assert write_clip([], tmp_path) is None


def test_clip_written(tmp_path):
    frames = [(float(i), np.full((120, 160, 3), i * 5, np.uint8)) for i in range(10)]
    p = write_clip(frames, tmp_path)
    assert p is not None and p.exists() and p.stat().st_size > 0
    assert p.name.startswith("clip_") and p.suffix == ".mp4"


def test_cleanup_deletes_old_only(tmp_path):
    old, new = tmp_path / "old.jpg", tmp_path / "new.jpg"
    old.write_bytes(b"x")
    new.write_bytes(b"x")
    os.utime(old, (0, 0))
    assert cleanup_old(tmp_path) == 1
    assert new.exists() and not old.exists()


def test_cleanup_missing_dir(tmp_path):
    assert cleanup_old(tmp_path / "nope") == 0
