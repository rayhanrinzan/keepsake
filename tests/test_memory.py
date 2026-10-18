"""ItemMemory (worn camera) and grounded lookups. All inputs are synthetic detections."""
from datetime import timedelta

from catalog import CATALOG
from conftest import BED, DESK, T0, Clock, obs
from database import Database
from memory import ItemMemory, answer_query, parse_query


def test_catalog_has_the_demo_objects_and_aliases():
    names = [c["name"] for c in CATALOG]
    assert names == ["Water Bottle", "Keys", "Wallet", "AirPods", "Glasses", "Backpack"]
    assert all(0.1 <= c["min_conf"] <= 0.9 for c in CATALOG)
    for c in CATALOG:
        assert parse_query(f"where is my {c['name'].lower()}")[0] == c["category"]
        for alias in c["aliases"]:
            assert parse_query(f"where's my {alias}?")[0] == c["category"], alias


def test_steady_sighting_creates_memory_without_any_place(clock, db):
    events = clock.frames(4, obs("bottle", DESK))
    assert [e["event_type"] for e in events] == ["first_seen"]
    rec = db.get_by_category("bottle")
    assert rec["visible"] and rec["last_seen"]
    assert (rec["region"], rec["x"], rec["y"]) == (None, None, None)  # a worn camera's screen spot


def test_single_frame_false_hit_never_counts(clock, db):
    clock.frames(1, obs("wallet"))
    clock.wait(3)
    clock.frames(1, obs("wallet"))
    assert db.get_by_category("wallet") is None


def test_seeing_it_elsewhere_on_screen_is_never_a_move(clock, db):
    clock.frames(4, obs("bottle", DESK))
    events = clock.frames(10, obs("bottle", BED))  # the wearer turned; same item
    assert events == [] and db.get_events() == []  # no movement history from a moving camera
    assert db.get_by_category("bottle")["region"] is None


def test_last_seen_updates_while_in_view_and_goes_out_of_view(clock, db):
    clock.frames(4, obs())
    first = db.get_by_category("bottle")["last_seen"]
    clock.frames(5, obs())
    assert db.get_by_category("bottle")["last_seen"] > first
    clock.frames(15)  # 3 s without it
    rec = db.get_by_category("bottle")
    assert not rec["visible"] and rec["last_seen"] > first


def test_low_confidence_and_unknown_classes_ignored(clock, db):
    clock.frames(10, obs("bottle", conf=0.2), obs("umbrella"), obs("person", size=0.4))
    assert db.get_objects() == []


def test_per_item_confidence_thresholds(clock, db):
    clock.frames(10, obs("glasses", conf=0.22))  # typical open-vocabulary false hit
    assert db.get_by_category("glasses") is None
    clock.frames(6, obs("car key", conf=0.32, tid=3))  # under the keys cutoff (0.5)
    assert db.get_by_category("car key") is None
    clock.frames(6, obs("car key", conf=0.6, tid=3))
    assert db.get_by_category("car key")["visible"]


def test_independent_items_and_tracker_id_swaps(clock, db):
    clock.frames(4, obs("bottle", tid=1), obs("backpack", BED, tid=2))
    clock.frames(4, obs("bottle", tid=9))  # new tracker id, same category: same item
    assert {r["category"] for r in db.get_objects()} == {"bottle", "backpack"}
    assert len(clock.events) == 2


def test_persistence_and_clear(tmp_path, db):
    m = ItemMemory(db)
    Clock(m).frames(4, obs())
    again = ItemMemory(Database(tmp_path / "t.db"))
    assert again.db.get_by_category("bottle") is not None and again.view_id == m.view_id
    m.reset()
    assert db.get_objects() == []


def test_window_uses_time_not_just_frames(db):
    m = ItemMemory(db, stability=3, settle_seconds=1.0)
    c = Clock(m)
    for _ in range(3):  # three hits, but 2 s apart: never steady
        c.frames(1, obs())
        c.wait(2)
    assert db.get_by_category("bottle") is None


def _lookup(db, photo=False):
    def lookup(category):
        rec = db.get_by_category(category)
        if not rec:
            return {"seen": False}
        return {"seen": True, "last_seen": rec["last_seen"], "visible": bool(rec["visible"]),
                "snapshot": {"id": 1} if photo else None}
    return lookup


def test_query_answers_cite_time_and_photo_never_a_place(clock, db):
    assert answer_query("where are my keys", _lookup(db))["answer"] == "I haven't seen your keys yet."
    clock.frames(4, obs("bottle"))
    r = answer_query("my water bottle", _lookup(db, photo=True))
    assert r["found"] and r["answer"].startswith("I last saw your water bottle ") and " at " in r["answer"]
    assert "The last photo is in Keepsake." in r["answer"] and "in view right now" in r["answer"]
    clock.frames(15)
    r = answer_query("water bottle", _lookup(db))
    assert r["answer"].endswith("It may have moved since.")
    for word in ("desk", "couch", "on the", "near", "side of"):
        assert word not in r["answer"].lower()
    bad = answer_query("where is my umbrella", _lookup(db))
    assert not bad["found"] and bad["category"] is None and "water bottle" in bad["answer"]


def test_query_parsing_prefers_longest_alias():
    assert parse_query("where are my car keys")[0] == "car key"
    assert parse_query("where's my airpods case")[0] == "airpods case"
    assert parse_query("my water bottle")[0] == "bottle"
    assert parse_query("where is my umbrella") is None


def test_answer_says_yesterday_for_old_sightings(db):
    m = ItemMemory(db)
    c = Clock(m, start=T0 - timedelta(days=1))
    c.frames(4, obs())
    r = answer_query("bottle", _lookup(db))
    assert "yesterday" in r["answer"] or " on " in r["answer"]
