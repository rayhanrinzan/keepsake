"""SpatialMemory state machine and lookup. All inputs are synthetic detections, not camera data."""
from datetime import timedelta

from catalog import ALIASES, CATALOG
from conftest import BED, DESK, DRESSER, T0, Clock, obs
from database import Database
from memory import SpatialMemory, answer_query, parse_query
from spatial import region_for_point


def test_catalog_has_the_eight_objects_and_aliases():
    names = [c["name"] for c in CATALOG]
    assert names == ["Phone", "Water Bottle", "Keys", "Wallet", "AirPods", "Glasses", "Laptop", "Cup",
                     "Book", "Backpack", "Remote", "Mouse"]
    assert all(0.1 <= c["min_conf"] <= 0.9 for c in CATALOG)
    for c in CATALOG:
        assert parse_query(f"where is my {c['name'].lower()}")[0] == c["category"]
        for alias in c["aliases"]:
            assert parse_query(f"where's my {alias}?")[0] == c["category"], alias


def test_region_assignment(regions):
    assert region_for_point(*DESK, regions) == "Desk"
    assert region_for_point(*DRESSER, regions) == "Dresser"
    assert region_for_point(*BED, regions) == "Bed"
    assert region_for_point(1.5, 0.5, regions) is None


def test_stable_first_detection_creates_memory(clock, db):
    assert clock.frames(3, obs()) == []  # not settled yet
    assert db.get_by_category("bottle") is None
    [ev] = clock.frames(3, obs())
    assert ev["event_type"] == "first_seen" and ev["region"] == "Desk"
    rec = db.get_by_category("bottle")
    assert rec["region"] == "Desk" and rec["visible"] and rec["name"] == "Water Bottle"


def test_move_between_regions(clock, db):
    clock.frames(6, obs(pos=DESK))
    clock.frames(4, obs(pos=(0.3, 0.5)))  # being carried: positions keep jumping
    clock.frames(2, obs(pos=(0.42, 0.45)))
    evs = clock.frames(6, obs(pos=DRESSER))
    assert [e["event_type"] for e in evs] == ["moved"]
    assert evs[0]["from_region"] == "Desk" and evs[0]["to_region"] == "Dresser"
    assert db.get_by_category("bottle")["region"] == "Dresser"
    assert db.get_events()[0]["event_type"] == "moved"


def test_significant_move_within_region(clock, db):
    clock.frames(6, obs(pos=(0.08, 0.3)))
    [ev] = clock.frames(6, obs(pos=(0.25, 0.75)))  # still Desk, but ~0.5 away
    assert ev["event_type"] == "moved_within" and ev["region"] == "Desk"
    rec = db.get_by_category("bottle")
    assert (rec["x"], rec["y"]) == (0.25, 0.75)


def test_minor_jitter_is_ignored(clock, db):
    clock.frames(6, obs(pos=DESK))
    for dx in (0.01, -0.012, 0.02, -0.015, 0.0, 0.018) * 3:
        clock.frames(1, obs(pos=(DESK[0] + dx, DESK[1] - dx)))
    assert len(db.get_events()) == 1  # only the first sighting


def test_brief_flicker_to_other_region_is_ignored(clock, db):
    clock.frames(6, obs(pos=DESK))
    clock.frames(2, obs(pos=DRESSER))
    clock.frames(1, obs(pos=DESK))
    clock.frames(2, obs(pos=DRESSER))
    clock.frames(3, obs(pos=DESK))
    assert db.get_by_category("bottle")["region"] == "Desk"
    assert len(db.get_events()) == 1


def test_no_confirmation_while_local_motion_continues(clock, db):
    clock.frames(10, obs(motion=0.3))  # a hand still fiddling with it
    assert db.get_by_category("bottle") is None
    assert clock.frames(1, obs(motion=0.0))[0]["event_type"] == "first_seen"


def test_unrelated_motion_and_people_create_no_events(clock, db):
    clock.frames(6, obs(pos=DESK))
    person = obs(cat="person", pos=(0.7, 0.5), size=0.5)
    clock.frames(20, obs(pos=DESK), person)  # someone walks past; the bottle stays put
    clock.frames(5, person)
    assert len(db.get_events()) == 1 and len(clock.events) == 1


def test_snapshot_frame_avoids_person_covering_object(clock):
    hand = obs(cat="person", pos=DESK, size=0.4)
    clock.frames(3, obs(conf=0.95), hand)  # covered but very confident
    [ev] = clock.frames(3, obs(conf=0.7))
    assert ev["occluded"] is False and ev["frame_id"] in (4, 5, 6)


def test_low_confidence_and_unknown_classes_ignored(clock, db):
    clock.frames(10, obs(conf=0.2))
    clock.frames(10, obs(cat="toaster"))
    assert db.get_objects() == []


def test_missing_detections_never_invent_locations(clock, db):
    clock.frames(20)  # nothing detected at all
    assert db.get_objects() == [] and db.get_events() == []
    assert answer_query("where is my water bottle", db)["answer"] == \
        "I haven't seen your water bottle yet."


def test_object_leaving_view_keeps_last_location(clock, db):
    clock.frames(6, obs(pos=DRESSER))
    clock.frames(15)  # gone for 3 s
    rec = db.get_by_category("bottle")
    assert rec["region"] == "Dresser" and rec["visible"] is False
    assert rec["lost_while_moving"] is False
    assert "out of view now" in answer_query("Where is my bottle?", db)["answer"]


def test_object_carried_out_of_view_mid_move(clock, db):
    clock.frames(6, obs(pos=DESK))
    clock.frames(3, obs(pos=(0.25, 0.4)))  # picked up; not settled
    clock.frames(15)
    rec = db.get_by_category("bottle")
    assert rec["region"] == "Desk" and rec["visible"] is False and rec["lost_while_moving"]
    assert "being moved when it left" in answer_query("water bottle?", db)["answer"]
    assert len(db.get_events()) == 1  # no fake 'moved' event


def test_tracker_id_change_reassociates_by_category(clock, db):
    clock.frames(6, obs(pos=DESK, tid=1))
    clock.frames(6, obs(pos=BED, tid=42))
    rec = db.get_by_category("bottle")
    assert rec["region"] == "Bed" and rec["track_id"] == 42 and len(db.get_objects()) == 1


def test_independent_objects_tracked_separately(clock, db):
    clock.frames(6, obs("bottle", DESK), obs("cell phone", BED, tid=2))
    clock.frames(6, obs("bottle", DRESSER), obs("cell phone", BED, tid=2))
    assert db.get_by_category("bottle")["region"] == "Dresser"
    assert db.get_by_category("cell phone")["region"] == "Bed"
    assert [e["event_type"] for e in clock.events] == ["first_seen", "first_seen", "moved"]


def test_persistence_across_reinit(tmp_path, regions):
    path = tmp_path / "p.db"
    d1 = Database(path)
    m1 = SpatialMemory(d1, regions)
    Clock(m1).frames(6, obs(pos=DRESSER))
    view = m1.view_id
    d1.close()
    d2 = Database(path)
    m2 = SpatialMemory(d2, regions)
    assert d2.get_by_category("bottle")["region"] == "Dresser"
    assert m2.view_id == view and len(d2.get_events()) == 1
    d2.close()


def test_clear_memory(mem, clock, db):
    clock.frames(6, obs())
    mem.reset()
    assert db.get_objects() == [] and db.get_events() == []


def test_pause_blocks_all_updates(mem, clock, db):
    clock.frames(6, obs(pos=DESK))
    mem.pause()
    assert clock.frames(20, obs(pos=BED)) == []
    assert db.get_by_category("bottle")["region"] == "Desk"


def test_new_view_reobservation_is_not_a_move(mem, clock, db):
    clock.frames(6, obs(pos=DESK))
    mem.pause()
    clock.frames(10, obs(pos=BED))  # camera being moved around
    mem.resume(new_view=True)
    assert "before the camera was repositioned" in answer_query("bottle", db, mem.view_id)["answer"]
    [ev] = clock.frames(6, obs(pos=(0.6, 0.3)))  # same bottle, new pixel position
    assert ev["event_type"] == "reconfirmed"
    assert [e["event_type"] for e in db.get_events()] == ["first_seen"]  # no false movement
    rec = db.get_by_category("bottle")
    assert rec["view_id"] == mem.view_id and rec["region"] == "Dresser"


def test_camera_shift_suspension_drops_candidates(mem, clock, db):
    clock.frames(6, obs(pos=DESK))
    clock.frames(3, obs(pos=BED))
    mem.suspend(3.0, now=clock.t)
    clock.frames(10, obs(pos=BED))  # suspended for 2 s of these frames
    assert db.get_by_category("bottle")["region"] == "Desk"


def test_query_answers_are_grounded(clock, db):
    unknown = answer_query("Where is my umbrella?", db)
    assert unknown["found"] is False and "didn't catch" in unknown["answer"]
    assert answer_query("Where is my phone?", db)["answer"] == "I haven't seen your phone yet."
    clock.frames(6, obs(pos=DRESSER))
    r = answer_query("My water bottle", db)
    assert r["found"] and r["object"]["region"] == "Dresser"
    assert r["answer"].startswith("I last saw your water bottle on the dresser ")
    assert ":30 AM" in r["answer"] or ":30 PM" in r["answer"]  # T0 in local time
    assert r["answer"].endswith("It's in view right now.")


def test_query_parsing_prefers_longest_alias():
    assert parse_query("where is my computer mouse")[0] == "mouse"
    assert parse_query("where's my laptop")[0] == "laptop"
    assert parse_query("my notebook")[0] == "book"
    assert parse_query("where is my umbrella") is None


def test_settle_window_uses_time_not_just_frames(db, regions):
    m = SpatialMemory(db, regions, stability=2, settle_seconds=0.8)
    c = Clock(m)
    c.frames(3, obs())  # 3 frames spanning 0.4 s
    assert db.get_by_category("bottle") is None
    c.wait(0.5)
    assert c.frames(1, obs())[0]["event_type"] == "first_seen"
    assert T0 < c.t < T0 + timedelta(seconds=2)


def test_locate_adapts_to_whatever_areas_exist():
    from spatial import Region, locate, place_phrase
    couch = Region("Couch", 0.1, 0.5, 0.5, 0.9, kind="couch")
    table = Region("Table", 0.3, 0.6, 0.45, 0.8, kind="dining table")
    tv = Region("TV", 0.7, 0.1, 0.9, 0.3, kind="tv")
    areas = [couch, table, tv]
    assert locate(0.35, 0.7, areas) == "Table"  # most specific area wins
    assert locate(0.2, 0.6, areas) == "Couch"
    assert locate(0.55, 0.7, areas) == "Near Couch"
    assert locate(0.95, 0.95, areas) == "Right side"
    assert locate(0.1, 0.1, []) == "Left side" and locate(0.5, 0.5, []) == "Middle"
    assert place_phrase("Couch", areas) == "on the couch"
    assert place_phrase("TV", areas) == "by the tv"
    assert place_phrase("Near Couch", areas) == "near the couch"
    assert place_phrase("Left side") == "on the left side of the room"


def test_no_areas_still_gives_honest_locations(db):
    m = SpatialMemory(db, [])
    Clock(m).frames(6, obs(pos=(0.1, 0.5)))
    assert db.get_by_category("bottle")["region"] == "Left side"
    assert "on the left side of the room" in answer_query("bottle", db, regions=[])["answer"]


def test_per_item_confidence_thresholds(clock, db):
    clock.frames(10, obs("glasses_case", conf=0.22))  # typical open-vocabulary false hit
    assert db.get_by_category("glasses_case") is None
    clock.frames(6, obs("keys", pos=(0.5, 0.5), conf=0.32, tid=3))
    assert db.get_by_category("keys")["region"] == "Dresser"
    assert parse_query("where are my airpods")[0] == "airpods"
    assert parse_query("have you seen my wallet")[0] == "wallet"
