from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from database import Database
from memory import Observation, SpatialMemory
from snapshots import SnapshotStore
from spatial import Region

T0 = datetime(2026, 10, 15, 14, 30, tzinfo=timezone.utc)
STEP = timedelta(seconds=0.2)  # ~5 fps, like the live worker
DESK, DRESSER, BED = (0.15, 0.5), (0.5, 0.5), (0.85, 0.5)


def obs(cat="bottle", pos=DESK, conf=0.9, motion=0.0, tid=1, size=0.06):
    x, y = pos
    return Observation(cat, conf, x, y, track_id=tid, motion=motion,
                       bbox=(x - size / 2, y - size / 2, x + size / 2, y + size / 2))


class Clock:
    """Feeds synthetic frames to SpatialMemory at a fixed rate; collects confirmed events."""

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


# Hand-drawn test areas (live areas come from Scan room).
TEST_AREAS = [Region("Desk", 0.0, 0.0, 0.333, 1.0), Region("Dresser", 0.333, 0.0, 0.667, 1.0),
              Region("Bed", 0.667, 0.0, 1.0, 1.0, kind="bed")]


@pytest.fixture
def regions():
    return list(TEST_AREAS)


@pytest.fixture
def db(tmp_path):
    d = Database(tmp_path / "t.db")
    yield d
    d.close()


@pytest.fixture
def mem(db, regions):
    return SpatialMemory(db, regions, stability=4, settle_seconds=0.8, absence_seconds=2)


@pytest.fixture
def clock(mem):
    return Clock(mem)


@pytest.fixture
def store(db, tmp_path):
    return SnapshotStore(db, tmp_path / "snaps", retention=3, cooldown_seconds=3)


@pytest.fixture
def frame():
    return np.full((360, 640, 3), 128, np.uint8)
