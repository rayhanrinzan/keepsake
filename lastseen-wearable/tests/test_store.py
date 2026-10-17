from lastseen.bus import Bus
from lastseen.memory.store import Store
from lastseen.types import TrackerEvent


def make_store(tmp_path):
    bus = Bus()
    q = bus.subscribe()
    return Store(str(tmp_path / "sub" / "db.sqlite"), bus), q


def test_add_event_publishes_and_returns_id(tmp_path):
    s, q = make_store(tmp_path)
    eid = s.add_event(TrackerEvent("PLACED", "airpods", 1.0, "tray", "desk", (1, 2, 3, 4), 0.9),
                      snapshot_path="/x/y/snap.jpg")
    assert eid == 1
    m = q.get(timeout=1)
    assert m["type"] == "event" and "ts" in m
    ev = m["event"]
    assert ev["to_zone"] == "desk" and ev["id"] == 1 and ev["bbox"] == [1, 2, 3, 4]
    assert ev["snapshot_url"] == "/clips/snap.jpg" and ev["clip_url"] is None
    assert ev["uncertain"] is False and ev["ts"] == 1.0


def test_uncertain_derived_from_confidence(tmp_path):
    s, _ = make_store(tmp_path)
    s.add_event(TrackerEvent("PLACED", "airpods", 1.0, None, "desk", (1, 2, 3, 4), 0.5))
    assert s.recent_events(1)[0]["uncertain"] is True


def test_recent_and_last_event(tmp_path):
    s, _ = make_store(tmp_path)
    for i, k in enumerate(["PICKED_UP", "PLACED", "HIDDEN"]):
        s.add_event(TrackerEvent(k, "a", float(i), None, "z", None, 0.9))
    s.add_event(TrackerEvent("PLACED", "b", 9.0, None, "z", None, 0.9))
    assert [e["kind"] for e in s.recent_events(10, "a")] == ["HIDDEN", "PLACED", "PICKED_UP"]
    assert s.recent_events(1)[0]["item_id"] == "b"
    assert s.last_event("a", ("PLACED", "PICKED_UP"))["kind"] == "PLACED"
    assert s.last_event("a", ("CARRIED_OUT",)) is None
    assert s.recent_events(1, "a")[0]["bbox"] is None


def test_upsert_item_publishes_and_gets(tmp_path):
    s, q = make_store(tmp_path)
    s.upsert_item("airpods", "AirPods", True, "PLACED", "desk", (1, 2, 3, 4), 0.4, 5.0)
    m = q.get(timeout=1)
    assert m["type"] == "item_update"
    it = m["item"]
    assert it["id"] == "airpods" and it["critical"] is True and it["uncertain"] is True
    got = s.get_item("airpods")
    assert got["bbox"] == [1, 2, 3, 4] and got["state"] == "PLACED"
    assert s.get_item("nope") is None
    s.upsert_item("airpods", "AirPods", True, "HELD", None, None, 0.9, 6.0)
    assert len(s.list_items()) == 1 and s.get_item("airpods")["state"] == "HELD"


def test_state_survives_restart(tmp_path):
    s, _ = make_store(tmp_path)
    s.upsert_item("airpods", "AirPods", False, "PLACED", "desk", (1, 2, 3, 4), 0.9, 5.0)
    s2 = Store(str(tmp_path / "sub" / "db.sqlite"), Bus())
    assert s2.get_item("airpods")["zone"] == "desk"


def test_asks(tmp_path):
    s, _ = make_store(tmp_path)
    aid = s.add_ask("voice", "where?", "airpods", "on desk", "PLACED", "desk", 12)
    assert aid == 1
    a = s.recent_asks(5)
    assert a[0]["question"] == "where?" and a[0]["latency_ms"] == 12


def test_reset_keeps_items_clears_events(tmp_path):
    s, _ = make_store(tmp_path)
    s.upsert_item("airpods", "AirPods", False, "PLACED", "desk", (1, 2, 3, 4), 0.9, 5.0, 1)
    s.add_event(TrackerEvent("PLACED", "airpods", 1.0, None, "desk", None, 0.9))
    s.add_ask("voice", "q", "airpods", "a", "PLACED", "desk", 1)
    s.reset_states()
    it = s.get_item("airpods")
    assert it is not None and it["state"] == "UNKNOWN"
    assert s.recent_events() == [] and s.recent_asks() == []
