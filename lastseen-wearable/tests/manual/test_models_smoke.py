"""Loads the real models. Run: .venv/bin/python -m pytest --run-models tests/manual -q -s"""
import numpy as np
import pytest

from lastseen.config import load_config
from lastseen.vision.detector import Detector
from lastseen.vision.embedder import ClipEmbedder

pytestmark = pytest.mark.models


def test_detector_and_embedder_shapes():
    cfg = load_config("config.yaml")
    frame = np.full((480, 640, 3), 120, np.uint8)
    frame[200:260, 300:380] = 240
    det = Detector(cfg)
    det.set_items(cfg.items)
    dets = det.detect(frame)
    print("detections:", len(dets), dets[:3])
    assert isinstance(dets, list)
    assert all(isinstance(d[0], str) and len(d[1]) == 4 for d in dets)
    emb = ClipEmbedder(cfg.device, cfg.paths.models, cfg.identity.crop_pad)
    e = emb.embed(frame, [(300, 200, 380, 260), (0, 0, 100, 100)])
    print("embed shape:", e.shape, "norms:", np.linalg.norm(e, axis=1))
    assert e.shape == (2, 512)
    assert np.allclose(np.linalg.norm(e, axis=1), 1, atol=1e-4)
    assert emb.embed(frame, []).shape == (0, 512)
    t = emb.embed_text(["airpods case", "glasses", "playing cards", "a hand"])
    print("embed_text shape:", t.shape, "norms:", np.linalg.norm(t, axis=1))
    assert t.shape == (4, 512)
    assert np.allclose(np.linalg.norm(t, axis=1), 1, atol=1e-4)


def test_hand_detector_runs():
    from lastseen.vision.hands import HandDetector
    hd = HandDetector("models/hand_landmarker.task")
    frame = np.full((480, 640, 3), 120, np.uint8)
    out = hd.detect(frame, 1000)
    out2 = hd.detect(frame, 1000)  # non-increasing ts must not raise
    print("hand boxes:", out, out2)
    assert isinstance(out, list) and isinstance(out2, list)
    hd.close()


def test_people_tracker_runs():
    from lastseen.vision.people import PeopleTracker
    cfg = load_config("config.yaml")
    pt = PeopleTracker(cfg.persons, cfg.device)
    frame = np.full((480, 640, 3), 120, np.uint8)
    persons, det = pt.track(frame)
    print("persons:", persons, "dets:", len(det))
    assert persons == [] and len(det) == 0
