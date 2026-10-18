from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import numpy as np
import pytest

from database import Database
from memory import ItemMemory, Observation
from snapshots import SnapshotStore

T0 = datetime(2026, 10, 15, 14, 30, tzinfo=timezone.utc)
STEP = timedelta(seconds=0.2)  # ~5 fps, like the live worker
# Screen points for synthetic boxes. They mean nothing about the room: the camera is worn.
DESK, DRESSER, BED = (0.15, 0.5), (0.5, 0.5), (0.85, 0.5)


def obs(cat="bottle", pos=DESK, conf=0.9, motion=0.0, tid=1, size=0.06):
    x, y = pos
    return Observation(cat, conf, x, y, track_id=tid, motion=motion,
                       bbox=(x - size / 2, y - size / 2, x + size / 2, y + size / 2))


class Clock:
    """Feeds synthetic frames to ItemMemory at a fixed rate; collects its events."""

    def __init__(self, mem, start=T0):
        self.mem, self.t, self.frame, self.events = mem, start, 0, []

    def frames(self, n, *observations):
        out = []
        for _ in range(n):
            self.frame += 1
            out += self.mem.observe(list(observations), now=self.t, frame_id=self.frame)
            self.t += STEP
        self.events += out
        return out

    def wait(self, seconds):
        self.t += timedelta(seconds=seconds)


class Pipeline:
    """Synthetic frames through the live worker's path: memory, the wearable observer, and
    VisionWorker._record (observation event + photo). Tests only; never live data."""

    def __init__(self, memory, snapshots, start=T0, camera_motion=0.0):
        from vision import VisionWorker
        from wearable import WearableObserver
        self.memory, self.snapshots, self.t, self.frame_id = memory, snapshots, start, 0
        self.observer = WearableObserver()
        self.camera_motion = camera_motion
        self.image = np.full((360, 640, 3), 100, np.uint8)
        self._worker = SimpleNamespace(memory=memory, snapshots=snapshots,
                                       _frame_for=lambda _fid: self.image)
        self._record = VisionWorker._record

    def frames(self, n, *observations):
        events = []
        for _ in range(n):
            self.frame_id += 1
            self.memory.observe(list(observations), now=self.t, frame_id=self.frame_id)
            for ev in self.observer.update(list(observations), self.t, self.frame_id,
                                           self.camera_motion, self.memory.view_id):
                self._record(self._worker, ev)
                events.append(ev)
            self.t += STEP
        self.snapshots.flush()
        return events


@pytest.fixture
def db(tmp_path):
    d = Database(tmp_path / "t.db")
    yield d
    d.close()


@pytest.fixture
def mem(db):
    return ItemMemory(db, stability=3, settle_seconds=1.0, absence_seconds=2)


@pytest.fixture
def clock(mem):
    return Clock(mem)


@pytest.fixture
def store(db, tmp_path):
    return SnapshotStore(db, tmp_path / "snaps", retention=3, cooldown_seconds=3)


@pytest.fixture
def frame():
    return np.full((360, 640, 3), 128, np.uint8)


@pytest.fixture(autouse=True)
def _no_vision_calls(monkeypatch):
    """Never send photos to xAI from tests (the repo .env may hold a real key)."""
    monkeypatch.setenv("CTRLF_DESCRIBE", "0")
