"""Scan room proposals from (synthetic) per-frame furniture detections."""
from furniture import propose_regions

BED = ("bed", 0.8, (0.5, 0.4, 0.95, 0.9))
CHAIR_A = ("chair", 0.6, (0.05, 0.5, 0.15, 0.8))
CHAIR_B = ("chair", 0.55, (0.2, 0.5, 0.3, 0.8))
TABLE = ("dining table", 0.5, (0.02, 0.45, 0.4, 0.7))


def jitter(det, d):
    k, c, b = det
    return (k, c, (b[0] + d, b[1], b[2] + d, b[3]))


def test_consistent_furniture_becomes_named_areas():
    frames = [[jitter(BED, d), jitter(CHAIR_A, d), jitter(CHAIR_B, -d), TABLE] for d in (0, 0.01, -0.01, 0.005, 0)]
    areas = propose_regions(frames)
    names = [a["name"] for a in areas]
    assert names[0] == "Bed"  # largest first
    assert set(names) == {"Bed", "Table", "Chair 1", "Chair 2"}
    bed = areas[0]
    assert bed["kind"] == "bed" and bed["camera"][0] < 0.5 < bed["camera"][2]


def test_flickering_and_non_furniture_detections_are_dropped():
    frames = [[BED], [BED], [BED, CHAIR_A], [BED], [BED, ("cup", 0.9, (0.1, 0.1, 0.2, 0.2))]]
    assert [a["name"] for a in propose_regions(frames)] == ["Bed"]


def test_empty_room_proposes_nothing():
    assert propose_regions([[], [], []]) == []
