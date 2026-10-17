"""Shared test fakes."""
import time

import numpy as np


class FakeCamera:
    def __init__(self, frame=None, ok=True, fps=30.0):
        self.frame = frame
        self.ok = ok
        self.fps = fps
        self._seq = 0

    def get_latest(self):
        if self.frame is None:
            return None, 0.0, 0
        self._seq += 1
        return self.frame, time.time(), self._seq


def solid_frame(h=120, w=160, value=200):
    return np.full((h, w, 3), value, np.uint8)


class FakeEmbedder:
    """Deterministic, no-ML embedder: a crop's mean BGR colour maps to a unit vector.

    Energy sits in a bin chosen by the quantized colour (4 levels per channel), plus a small
    brightness component, so white and mid-gray crops are nearly orthogonal and identical
    colours give cosine 1.
    """

    def __init__(self, crop_pad: float = 0.15):
        self.crop_pad = crop_pad
        self.calls = 0

    def embed(self, frame, boxes):
        self.calls += 1
        if not boxes:
            return np.zeros((0, 512), dtype=np.float32)
        h, w = frame.shape[:2]
        out = np.zeros((len(boxes), 512), dtype=np.float32)
        for i, (x1, y1, x2, y2) in enumerate(boxes):
            pad = int(self.crop_pad * max(x2 - x1, y2 - y1))
            x1, y1 = max(0, x1 - pad), max(0, y1 - pad)
            x2, y2 = min(w, x2 + pad), min(h, y2 + pad)
            crop = frame[y1:y2, x1:x2]
            mean = crop.reshape(-1, 3).mean(axis=0) if crop.size else np.zeros(3)
            q = np.minimum((mean / 64).astype(int), 3)
            out[i, int(q[0] * 16 + q[1] * 4 + q[2])] = 1.0
            out[i, 100] += mean.mean() / 255.0 * 0.2
            out[i] /= np.linalg.norm(out[i])
        return out

    def embed_text(self, texts):
        import zlib

        out = np.zeros((len(texts), 512), dtype=np.float32)
        for i, t in enumerate(texts):
            v = np.random.default_rng(zlib.crc32(t.encode())).standard_normal(512)
            out[i] = v / np.linalg.norm(v)
        return out


class FakeHands:
    """Scripted hand detector. `script` is a list of per-call box lists; the last entry repeats
    once exhausted. `raise_on` is a call index (0-based) or set of indices that raise."""

    def __init__(self, script=None, raise_on=None, fn=None):
        self.fn = fn  # optional fn(frame, ts_ms) -> boxes, used instead of the script
        self.script = list(script) if script else [[]]
        if raise_on is None:
            raise_on = set()
        elif isinstance(raise_on, int):
            raise_on = {raise_on}
        self.raise_on = set(raise_on)
        self.calls = 0

    def detect(self, frame, ts_ms):
        i = self.calls
        self.calls += 1
        if i in self.raise_on:
            raise RuntimeError(f"FakeHands scripted failure on call {i}")
        if self.fn is not None:
            return list(self.fn(frame, ts_ms))
        return list(self.script[min(i, len(self.script) - 1)])


class FakeDetector:
    """Scripted detector. `fn(frame) -> [(item_id|"*", box, conf)]`; records a copy of each frame."""

    def __init__(self, fn=None):
        self.fn = fn or (lambda frame: [])
        self.frames = []
        self.items_set = []  # item ids passed to each set_items call
        self.calls = 0

    def set_items(self, items, generic_prompts=None):
        self.items_set.append([i.id for i in items])

    def detect(self, frame):
        self.calls += 1
        self.frames.append(frame.copy())
        return list(self.fn(frame))


class FakePeople:
    """Scripted PeopleTracker: per-call lists of Person; the last entry repeats."""

    def __init__(self, script=None):
        self.script = list(script) if script else [[]]
        self.calls = 0

    def track(self, frame):
        import supervision as sv

        i = self.calls
        self.calls += 1
        return list(self.script[min(i, len(self.script) - 1)]), sv.Detections.empty()


class FakeClassifier:
    """Scripted ItemClassifier. `fn(frame, box, det_item_ids, candidates) -> Classification`."""

    def __init__(self, fn=None):
        from lastseen.vision.classify import Classification

        self.fn = fn or (lambda f, b, d, c: Classification(None, {"other": 1.0}, "other"))
        self.calls = []

    def classify(self, frame, box, det_item_ids, candidates):
        self.calls.append((tuple(box), list(det_item_ids), list(candidates)))
        return self.fn(frame, box, det_item_ids, candidates)


class FakeTouch:
    """Scripted TouchWatcher: per-call result lists (then []); records `enabled` per call."""

    def __init__(self, script=None):
        self.script = list(script) if script else []
        self.enabled = []

    def update(self, frame, ts, hands, enabled=True):
        self.enabled.append(enabled)
        if not enabled or not self.script:
            return []
        return list(self.script.pop(0))
