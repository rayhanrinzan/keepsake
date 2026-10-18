import json

import numpy as np
import pytest

from lastseen.engine.zones import Zone, ZoneMap

WH = (200, 100)


def rect(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


@pytest.fixture
def zm():
    return ZoneMap([
        Zone("desk", "surface", rect(0, 0, 0.5, 0.6)),
        Zone("bed", "cover", rect(0.6, 0, 1.0, 0.5)),
    ])


def test_zone_by_bottom_center(zm):
    # brief used (10,10,50,90); its bottom-center (30,90) is outside this desk
    assert zm.zone_at((10, 10, 50, 50), WH).name == "desk"
    assert zm.zone_at((180, 85, 196, 98), WH) is None


def test_cover_phrase(zm):
    assert zm.describe((130, 10, 170, 40), WH) == "under the blanket on the bed"


def test_surface_phrase(zm):
    assert zm.describe((10, 10, 50, 50), WH) == "on the desk"


def test_outside_all_zones_names_nearest(zm):
    assert zm.describe((40, 60, 60, 70), WH) == "on the floor near the desk"


def test_far_from_everything(zm):
    assert zm.describe((180, 85, 196, 98), WH) == "in the room"


def test_nearest(zm):
    z, d = zm.nearest((40, 60, 60, 70), WH)
    assert z.name == "desk" and d == pytest.approx(10)
    z, d = zm.nearest((10, 10, 50, 50), WH)
    assert d == 0


def test_privacy_excluded_and_mask():
    zm = ZoneMap([
        Zone("window", "privacy", rect(0, 0, 0.5, 0.5)),
        Zone("desk", "surface", rect(0, 0.5, 0.5, 1.0)),
    ])
    assert zm.zone_at((10, 10, 50, 40), WH) is None
    assert zm.describe((10, 10, 50, 40), WH) != "on the window"
    assert "window" not in zm.describe((10, 10, 50, 40), WH)
    m = zm.privacy_mask(WH)
    assert m.shape == (100, 200) and m.dtype == np.uint8
    assert m[10, 10] == 255 and m[80, 150] == 0
    assert ZoneMap([Zone("d", "surface", rect(0, 0, 1, 1))]).privacy_mask(WH) is None


def test_missing_file_empty(tmp_path):
    zm = ZoneMap.load(tmp_path / "nope.json")
    assert zm.zones == []
    assert zm.describe((10, 10, 50, 50), WH) == "in the room"
    assert zm.nearest((10, 10, 50, 50), WH)[0] is None


def test_cover_phrase_override_and_load(tmp_path):
    p = tmp_path / "z.json"
    p.write_text(json.dumps({"zones": [
        {"name": "bed", "type": "cover", "polygon": rect(0, 0, 1, 1),
         "cover_phrase": "inside the {name} drawer"}]}))
    zm = ZoneMap.load(p)
    assert zm.describe((10, 10, 50, 50), WH) == "inside the bed drawer"


GOOD = {"name": "desk", "type": "surface", "polygon": rect(0, 0, 1, 1)}


def _load(tmp_path, text):
    p = tmp_path / "z.json"
    p.write_text(text)
    return ZoneMap.load(p)


def test_unknown_type_skipped(tmp_path):
    zm = _load(tmp_path, json.dumps({"zones": [
        {"name": "door", "type": "exit", "polygon": rect(0, 0, 1, 1)}, GOOD]}))
    assert [z.name for z in zm.zones] == ["desk"]


def test_bad_json_gives_empty_map(tmp_path):
    assert _load(tmp_path, "{not json").zones == []
    assert _load(tmp_path, "[1, 2]").zones == []


def test_missing_key_skipped(tmp_path):
    zm = _load(tmp_path, json.dumps({"zones": [{"type": "surface", "polygon": rect(0, 0, 1, 1)},
                                               {"name": "x", "type": "surface"}, GOOD]}))
    assert [z.name for z in zm.zones] == ["desk"]


def test_two_point_polygon_skipped(tmp_path):
    zm = _load(tmp_path, json.dumps({"zones": [
        {"name": "line", "type": "surface", "polygon": [(0, 0), (1, 1)]},
        {"name": "junk", "type": "surface", "polygon": [(0, 0), "a", (1, 1)]}, GOOD]}))
    assert [z.name for z in zm.zones] == ["desk"]


def test_first_zone_wins_on_overlap():
    zm = ZoneMap([Zone("a", "surface", rect(0, 0, 1, 1)), Zone("b", "surface", rect(0, 0, 1, 1))])
    assert zm.zone_at((10, 10, 50, 50), WH).name == "a"


def test_zone_at_point(zm):
    assert zm.zone_at_point((50, 30), WH).name == "desk"
    assert zm.zone_at_point((150, 20), WH).type == "cover"
    assert zm.zone_at_point((190, 90), WH) is None
