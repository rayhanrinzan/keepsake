import time

import cv2
import numpy as np
import pytest

from lastseen.capture.camera import LatestFrameCamera
from lastseen.capture.ringbuffer import RingBuffer


@pytest.fixture
def video(tmp_path):
    path = tmp_path / "synthetic.mp4"
    w = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 10, (640, 360))
    for i in range(20):
        frame = np.full((360, 640, 3), 40, np.uint8)
        cv2.putText(frame, str(i), (20, 200), cv2.FONT_HERSHEY_SIMPLEX, 4, (255, 255, 255), 6)
        w.write(frame)
    w.release()
    return path


@pytest.fixture
def cams():
    made = []
    yield made
    for c in made:
        c.stop()


def test_replay_resizes_and_advances(video, cams):
    cam = LatestFrameCamera(0, 320, str(video))
    cams.append(cam)
    cam.start()
    time.sleep(0.5)
    f, ts, seq = cam.get_latest()
    assert f.shape[1] == 320 and f.shape[0] == 180
    assert seq > 0 and ts > 0
    assert cam.ok is True
    assert cam.fps > 0


def test_replay_loops_past_eof(video, cams):
    cam = LatestFrameCamera(0, 320, str(video))
    cams.append(cam)
    cam.start()
    time.sleep(2.6)  # video is 2 s long
    assert cam.get_latest()[2] > 20


def test_dead_source_does_not_raise(cams):
    cam = LatestFrameCamera("/nonexistent.mp4", 320, None)
    cams.append(cam)
    cam.start()
    time.sleep(0.5)
    assert cam.get_latest() == (None, 0.0, 0)
    assert cam.ok is False
    assert cam.fps == 0


def test_stop_joins_thread(video):
    cam = LatestFrameCamera(0, 320, str(video))
    cam.start()
    cam.stop()
    assert not cam._thread.is_alive()


def test_ringbuffer_window_and_eviction():
    rb = RingBuffer(1.0, 64)
    for i in range(20):
        rb.push(np.zeros((360, 640, 3), np.uint8), i * 0.1)
    # newest ts is 1.9, so anything older than 1.9 - 1.0 = 0.9 is evicted
    assert all(t >= 0.9 - 1e-6 for t, _ in rb.window(0, 99))
    assert rb.window(1.2, 1.5)[0][1].shape[1] == 64
    assert [round(t, 1) for t, _ in rb.window(1.2, 1.5)] == [1.2, 1.3, 1.4, 1.5]


class _FakeCap:
    """Stands in for cv2.VideoCapture on a live index; records the thread that opened it."""

    opened_on: list = []

    def __init__(self, src):
        import threading
        _FakeCap.opened_on.append(threading.current_thread().name)

    def isOpened(self):
        return True

    def set(self, *a):
        return True

    def read(self):
        time.sleep(0.01)
        return True, np.zeros((360, 640, 3), np.uint8)

    def release(self):
        pass


def test_live_camera_first_opened_on_calling_thread(monkeypatch):
    """macOS AVFoundation can't run its permission check off the main thread, so the first open must be on the caller's thread."""
    import threading
    import lastseen.capture.camera as camera_mod
    _FakeCap.opened_on = []
    monkeypatch.setattr(camera_mod.cv2, "VideoCapture", _FakeCap)
    cam = LatestFrameCamera(0, 320, None)
    cam.start()
    try:
        time.sleep(0.2)
        assert _FakeCap.opened_on[0] == threading.current_thread().name
        assert cam.get_latest()[0] is not None
    finally:
        cam.stop()


def test_skip_auth_env_set_for_thread_reopens():
    import os
    import lastseen.capture.camera  # noqa: F401
    assert os.environ.get("OPENCV_AVFOUNDATION_SKIP_AUTH") == "1"


def test_open_failure_is_logged(cams, caplog):
    cam = LatestFrameCamera("/nonexistent.mp4", 320, None)
    cams.append(cam)
    with caplog.at_level("WARNING", logger="lastseen.capture.camera"):
        cam.start()
        time.sleep(0.3)
    assert any("could not open camera" in r.getMessage() for r in caplog.records)


def test_find_camera_index_by_name():
    from lastseen.capture.devices import find_camera_index
    names = ["MacBook Pro Camera", "Roman's iPhone Camera"]
    assert find_camera_index("iphone", names) == 1
    assert find_camera_index("MacBook", names) == 0
    assert find_camera_index("iPhone", ["MacBook Pro Camera"]) is None


def test_named_source_resolves_to_index(monkeypatch):
    """camera.source "iPhone" opens the iPhone's current index, never the Mac camera."""
    import lastseen.capture.camera as camera_mod
    opened = []

    class Cap(_FakeCap):
        def __init__(self, src):
            opened.append(src)

    monkeypatch.setattr(camera_mod.cv2, "VideoCapture", Cap)
    monkeypatch.setattr(camera_mod, "find_camera_index", lambda name: 1 if name == "iPhone" else None)
    cam = LatestFrameCamera("iPhone", 320, None)
    cam.start()
    try:
        time.sleep(0.2)
        assert opened and opened[0] == 1
    finally:
        cam.stop()


def test_named_source_missing_waits_and_logs(monkeypatch, caplog):
    import lastseen.capture.camera as camera_mod
    opened = []
    monkeypatch.setattr(camera_mod.cv2, "VideoCapture", lambda src: opened.append(src))
    monkeypatch.setattr(camera_mod, "find_camera_index", lambda name: None)
    cam = LatestFrameCamera("iPhone", 320, None)
    with caplog.at_level("WARNING", logger="lastseen.capture.camera"):
        cam.start()
        time.sleep(0.3)
        cam.stop()
    assert opened == []  # never falls back to another camera
    assert any("iPhone" in r.getMessage() and "not found" in r.getMessage() for r in caplog.records)


def test_find_camera_prefers_exact_then_substring_skipping_desk_view():
    from lastseen.capture.devices import find_camera_index
    names = ["Roman's iPhone Desk View Camera", "Roman's iPhone Camera", "iPhone"]
    assert find_camera_index("IPHONE", names) == 2                      # exact, case-insensitive
    assert find_camera_index("Roman's iPhone", names) == 1               # substring, not Desk View
    assert find_camera_index("iphone", names[:1]) is None                # only a Desk View: no match
    assert find_camera_index("desk view", names) == 0                    # asked for it explicitly


def test_successful_open_logs_name_and_index(monkeypatch, caplog):
    import lastseen.capture.camera as camera_mod
    monkeypatch.setattr(camera_mod.cv2, "VideoCapture", _FakeCap)
    monkeypatch.setattr(camera_mod, "find_camera_index", lambda name: 3)
    cam = LatestFrameCamera("iPhone", 320, None)
    with caplog.at_level("INFO", logger="lastseen.capture.camera"):
        cam.start()
        cam.stop()
    msgs = [r.getMessage() for r in caplog.records if r.levelname == "INFO"]
    assert any("'iPhone'" in m and "index 3" in m for m in msgs), msgs


def test_device_names_follow_opencv_order_by_unique_id():
    # macOS lists cameras in a varying order; OpenCV 5 numbers them by uniqueID (observed live:
    # iPhone 266E... is index 0, MacBook 6C70... is index 1, whichever order macOS lists them in)
    from lastseen.capture.devices import ordered_names

    class D:
        def __init__(self, name, uid):
            self.n, self.u = name, uid

        def localizedName(self):
            return self.n

        def uniqueID(self):
            return self.u

    devs = [D("MacBook Pro Camera", "6C707041-05AC-0011-0009-000000000001"),
            D("iPhone Camera", "266E092C-690B-4C44-929C-968700000001")]
    assert ordered_names(devs) == ["iPhone Camera", "MacBook Pro Camera"]
    assert ordered_names(devs[::-1]) == ["iPhone Camera", "MacBook Pro Camera"]
