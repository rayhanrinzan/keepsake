"""Smart memory reminders: one policy engine, High-Assistance and Everyday presets.

Synthetic memory rows and events on a fake clock (tests only; never live data)."""
import importlib
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import events as E
from conftest import TEST_AREAS
from departure import DepartureFeed
from reminders import (CANCELLED, PENDING_REMINDER, PLACEMENT_CANDIDATE, POSSIBLE_INTERACTION,
                       REMINDER_SENT, EventError, ReminderEngine)
from spatial import save_regions

T0 = datetime(2026, 10, 17, 18, 30, tzinfo=timezone.utc).timestamp()
LOCAL = {"X-Keepsake-Local": "1"}


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).isoformat(timespec="seconds")


class Clock:
    def __init__(self, t=T0):
        self.t = t

    def __call__(self):
        return self.t


class World:
    """A database with Keepsake-shaped rows plus an engine on a fake clock."""

    def __init__(self, db, camera_mode="wearable", mode="high_assistance", status=None,
                 departures=None, enable=True):
        self.db, self.clock = db, Clock()
        self.memory = SimpleNamespace(view_id="view-a", paused=False, _suspended_until=None,
                                      states=lambda: {})
        self.modes = SimpleNamespace(mode="MONITORING")
        self.status = status if status is not None else {"camera": "active"}
        self.camera_mode = camera_mode
        self.engine = ReminderEngine(db, self.memory, self.modes, list(TEST_AREAS), departures,
                                     status_fn=lambda: self.status, clock=self.clock,
                                     camera_mode=camera_mode)
        if enable:
            self.engine.update_settings({"mode": mode, "enabled": True}, opt_in=True)
        self.alerts = []

    def photo(self, oid, event_type="object_observed", region="Bed", conf=0.8, view_id="view-a"):
        return self.db.add_snapshot({"object_id": oid, "event_type": event_type,
                                     "timestamp": iso(self.clock.t), "region": region,
                                     "x0": 0.7, "y0": 0.4, "x1": 0.9, "y1": 0.6, "confidence": conf,
                                     "filename": f"{oid}-{self.clock.t}-{event_type}.jpg",
                                     "view_id": view_id})

    def observe(self, etype, category="wallet", conf=0.8, evidence=None, photo=True):
        """A vision event exactly as vision.py records it (events.make_event -> observations
        table; the photo id is filled in after the async write)."""
        oid = f"{category.replace(' ', '_')}_01"
        default = {E.OBJECT_OBSERVED: ["stable_object_detection", "camera_steady"],
                   E.INTERACTION_CANDIDATE: ["hand_near_object", "camera_steady"],
                   E.POSSIBLE_PICKUP: ["hand_near_object", "object_moved_with_hand"],
                   E.PLACEMENT_CONFIRMED: ["prior_possible_pickup", "hand_released", "camera_steady"]}
        ev = E.make_event(etype, object_id=oid, category=category, name=category.title(),
                          timestamp=datetime.fromtimestamp(self.clock.t, timezone.utc),
                          confidence=conf, bbox=(0.7, 0.4, 0.9, 0.6),
                          evidence=evidence or default[etype],
                          camera_mode="fixed" if self.camera_mode == "fixed" else "wearable",
                          view_id="view-a")
        self.db.add_observation(ev)
        if photo and etype in (E.OBJECT_OBSERVED, E.PLACEMENT_CONFIRMED):
            self.db.set_observation_snapshot(ev["event_id"], self.photo(oid, etype, conf=conf))
        return ev

    def sight(self, category="wallet", visible=True, region="Bed", event_type="first_seen",
              conf=0.8, view_id="view-a", lost=False, photo=True):
        """The item is seen now: memory's object row, plus what the camera mode produces —
        wearable: an object_observed event with its photo; fixed: memory's own photo row."""
        oid = f"{category.replace(' ', '_')}_01"
        self.db.upsert_object({"object_id": oid, "category": category, "name": category.title(),
                               "region": region, "x": 0.8, "y": 0.5, "last_seen": iso(self.clock.t),
                               "visible": visible, "confidence": conf, "view_id": view_id,
                               "lost_while_moving": lost})
        if not photo:
            return None
        if self.camera_mode == "fixed":
            return self.photo(oid, event_type, region, conf, view_id)
        ev = self.observe(E.OBJECT_OBSERVED, category, conf)
        return self.db.get_observations(limit=1)[0]["snapshot_id"] if ev else None

    def hide(self, category="wallet"):
        """Memory marks the item out of view (last_seen stays at the last sighting)."""
        rec = self.db.get_by_category(category)
        rec["visible"] = False
        self.db.upsert_object(rec)

    def run(self, seconds, step=1.0):
        end = self.clock.t + seconds
        while self.clock.t < end:
            self.clock.t += step
            self.alerts += self.engine.tick()
        return self.alerts

    def state(self, category="wallet"):
        return self.engine._objs[f"{category.replace(' ', '_')}_01"]

    def deliver(self, alert, status="accepted"):
        self.engine.claim(alert["id"])
        return self.engine.report(alert["id"], status, None if status == "accepted" else "photon 503")

    def event(self, etype, eid, category="wallet", conf=0.9, snapshot_id=None, evidence=("hand",)):
        return self.engine.submit({"event_id": eid, "event_type": etype, "object_id": category,
                                   "timestamp": iso(self.clock.t), "confidence": conf,
                                   "snapshot_id": snapshot_id, "evidence": list(evidence),
                                   "camera_mode": "wearable"})


@pytest.fixture
def w(db):
    return World(db)


# ---------- opt-in and settings ----------

def test_reminders_are_off_by_default_and_need_explicit_opt_in(db):
    w = World(db, enable=False)
    assert w.engine.settings["enabled"] is False and w.engine.settings["mode"] == "off"
    w.sight()
    w.hide()
    assert w.run(60) == []
    with pytest.raises(PermissionError):
        w.engine.update_settings({"mode": "high_assistance", "enabled": True})
    s = w.engine.update_settings({"mode": "high_assistance", "enabled": True}, opt_in=True)
    assert s["active"] and s["settings"]["opted_in_at"]


def test_settings_persist_and_validate(db):
    w = World(db)
    w.engine.update_settings({"important": ["bottle", "Keys"],
                              "overrides": {"high_assistance": {"delay": 20}}})
    again = ReminderEngine(db, clock=w.clock)
    assert again.important() == ["bottle_01", "car_key_01"]
    assert again.policy()["delay"] == 20 and again.active()
    for bad in [{"mode": "loud"}, {"important": ["umbrella"]},
                {"overrides": {"everyday": {"tone": 1}}}, {"overrides": {"everyday": {"delay": -5}}}]:
        with pytest.raises(ValueError):
            w.engine.update_settings(bad)


# ---------- High-Assistance scheduling ----------

def test_high_assistance_reminds_after_short_delay_out_of_view(w):
    w.sight()
    w.run(2)
    assert w.state().state == PENDING_REMINDER and w.state().evidence == "object_observed"
    w.hide()
    w.run(10)
    assert w.alerts == []  # not yet: 15 s delay
    w.run(10)
    assert len(w.alerts) == 1
    a = w.alerts[0]
    assert a["trigger"] == "automatic" and a["mode"] == "high_assistance" and a["tone"] == "gentle"
    item = a["items"][0]
    assert item["object_id"] == "wallet_01" and item["snapshot_id"] and item["evidence"] == "object_observed"
    assert item["place"] is None  # wearable: no room location is claimed


def test_item_still_in_view_is_not_reminded(w):
    w.sight()
    w.run(120)
    assert w.alerts == []


def test_same_stationary_object_redetected_does_not_reset_the_timer(w):
    w.sight()
    w.run(1)
    episode, started = w.state().episode, w.state().started
    for _ in range(5):
        w.sight(event_type="reconfirmed")  # flicker: seen again, photo rows keep coming
        w.run(1)
    assert w.state().episode == episode and w.state().started == started
    w.hide()
    w.run(20)
    assert len(w.alerts) == 1 and len(w.alerts[0]["items"]) == 1


def test_one_reminder_per_placement_and_per_item_cooldown(w):
    w.sight()
    w.run(1)
    w.hide()
    w.run(20)
    w.deliver(w.alerts[0])
    assert w.state().state == REMINDER_SENT
    w.sight(event_type="reconfirmed")  # seen again soon after: same episode, no new reminder
    w.run(1)
    w.hide()
    w.run(120)
    assert len(w.alerts) == 1
    assert w.engine.submit({"event_id": "late", "event_type": "object_observed", "object_id": "wallet",
                            "timestamp": iso(w.clock.t), "confidence": 0.9})["why"] == "already_reminded"


def test_new_placement_after_reminder_still_respects_item_cooldown(w):
    snap = w.sight()
    w.run(1)
    w.hide()
    w.run(20)
    w.deliver(w.alerts[0])
    w.event("placement_confirmed", "p2", snapshot_id=w.sight(visible=False))
    w.run(30)
    assert len(w.alerts) == 1 and w.state().reason == "cooldown"
    assert snap


def test_multiple_items_are_combined_into_one_reminder(w):
    w.sight("wallet")
    w.sight("car key")
    w.run(1)
    w.hide("wallet")
    w.hide("car key")
    w.run(20)
    assert len(w.alerts) == 1
    assert sorted(i["object_id"] for i in w.alerts[0]["items"]) == ["car_key_01", "wallet_01"]


def test_global_cooldown_holds_the_next_reminder(w):
    w.sight("wallet")
    w.run(1)
    w.hide("wallet")
    w.run(20)
    w.deliver(w.alerts[0])
    w.sight("car key")
    w.run(1)
    w.hide("car key")
    w.run(20)
    assert len(w.alerts) == 1  # 60 s global cooldown
    w.run(40)
    assert len(w.alerts) == 2 and w.alerts[1]["items"][0]["object_id"] == "car_key_01"


def test_unwatched_items_are_ignored(w):
    w.sight("bottle")
    w.run(1)
    w.hide("bottle")
    w.run(30)
    assert w.alerts == []


def test_low_confidence_observation_is_not_scheduled(w):
    w.sight(conf=0.3)
    w.run(1)
    w.hide()
    w.run(30)
    assert w.alerts == [] and w.state().state != PENDING_REMINDER


# ---------- Everyday scheduling ----------

def test_everyday_ignores_plain_observations(db):
    w = World(db, mode="everyday")
    w.sight()
    w.run(1)
    w.hide()
    w.run(300, step=5)
    assert w.alerts == []


def test_everyday_reminds_after_confirmed_placement_and_long_delay(db):
    w = World(db, mode="everyday")
    snap = w.sight()
    assert w.event("placement_confirmed", "p1", snapshot_id=snap)["result"] == "scheduled"
    w.hide()
    w.run(120, step=5)
    assert w.alerts == []
    w.run(60, step=5)
    assert len(w.alerts) == 1 and w.alerts[0]["tone"] == "heading_out"
    assert w.alerts[0]["items"][0]["evidence"] == "placement_confirmed"


def test_everyday_rejects_weak_placement_confidence(db):
    w = World(db, mode="everyday")
    snap = w.sight()
    r = w.event("placement_confirmed", "p1", conf=0.5, snapshot_id=snap)
    assert r["why"] == "low_confidence"


# ---------- interaction evidence ----------

def test_hand_proximity_alone_does_not_cancel_or_schedule(w):
    snap = w.sight()
    w.run(1)
    assert w.event("interaction_candidate", "h1")["result"] == "recorded"
    assert w.state().state == PENDING_REMINDER  # still pending: proximity is not contact
    w.hide()
    w.run(20)
    assert len(w.alerts) == 1 and snap


def test_hand_near_then_stable_is_a_placement_candidate(db):
    w = World(db)
    w.engine.submit({"event_id": "h1", "event_type": "interaction_candidate", "object_id": "wallet",
                     "timestamp": iso(w.clock.t), "confidence": 0.7})
    assert w.state().state == POSSIBLE_INTERACTION
    w.clock.t += 5
    w.sight()
    w.run(1)
    assert w.state().state == PENDING_REMINDER and w.state().evidence == "interaction_then_stable"


def test_confident_pickup_cancels_pending_weak_one_does_not(w):
    w.sight()
    w.run(1)
    assert w.event("possible_pickup", "u1", conf=0.4)["result"] == "recorded"
    assert w.state().state == PENDING_REMINDER
    assert w.event("possible_pickup", "u2", conf=0.8)["result"] == "cancelled"
    assert w.state().state == CANCELLED and w.state().reason == "picked_up"
    w.hide()
    w.run(30)
    assert w.alerts == []


def test_newer_placement_supersedes_the_old_one(w):
    w.event("placement_confirmed", "p1", snapshot_id=w.sight())
    w.clock.t += 5
    w.event("placement_confirmed", "p2", snapshot_id=w.sight())
    assert w.state().episode == "p2"
    assert any(e["what"] == "cancelled" and e["reason"] == "superseded" for e in w.engine.log)
    w.hide()
    w.run(20)
    assert len(w.alerts) == 1 and w.alerts[0]["items"][0]["episode"] == "p2"


def test_duplicate_event_ids_are_ignored(w):
    snap = w.sight()
    assert w.event("placement_confirmed", "p1", snapshot_id=snap)["result"] == "scheduled"
    assert w.event("placement_confirmed", "p1", snapshot_id=snap)["result"] == "duplicate"


def test_placement_without_a_photo_waits_then_is_dropped(w):
    w.sight(photo=False)
    w.run(1)  # nothing from memory (no photo)
    assert w.event("placement_confirmed", "p1")["result"] == "candidate"
    assert w.state().state == PLACEMENT_CANDIDATE
    w.hide()
    w.run(30)
    assert w.alerts == [] and w.state().reason == "no_photo"


def test_snapshot_id_of_another_object_is_not_accepted(w):
    other = w.sight("car key")
    w.sight("wallet", photo=False)
    w.engine._snapshot_cursor = 10**9  # ignore the memory feed for this test
    assert w.event("placement_confirmed", "p1", snapshot_id=other)["result"] == "candidate"


def test_stale_photo_cancels(w):
    w.engine.update_settings({"overrides": {"high_assistance": {"max_photo_age": 10}}})
    w.sight()
    w.run(1)
    w.hide()
    w.run(20)
    assert w.alerts == [] and w.state().reason == "stale_photo"


def test_lost_while_moving_cancels(w):
    w.sight()
    w.run(1)
    w.sight(visible=False, lost=True, photo=False)
    w.run(20)
    assert w.alerts == [] and w.state().reason == "lost_while_moving"


def test_bad_events_are_rejected():
    e = ReminderEngine(SimpleNamespace(get_setting=lambda k: None, _lock=__import__("threading").Lock(),
                                       _conn=SimpleNamespace(execute=lambda *a: SimpleNamespace(
                                           fetchone=lambda: {"m": 0}))))
    good = {"event_id": "x", "event_type": "object_observed", "object_id": "wallet",
            "timestamp": "2026-10-17T18:30:00Z", "confidence": 0.9}
    assert e.normalize(good)["object_id"] == "wallet_01"
    for bad in [{"event_type": "teleported"}, {"event_id": ""}, {"object_id": "umbrella"},
                {"timestamp": "yesterday"}, {"confidence": 3}, {"snapshot_id": "a.jpg"},
                {"event_type": "placement_inferred"}]:
        with pytest.raises(EventError):
            e.normalize({**good, **bad})


# ---------- camera conditions ----------

def test_camera_motion_alone_does_not_cancel_on_a_wearable(db):
    w = World(db, status={"camera": "active", "camera_shift_at": T0 + 100})
    w.sight()
    w.run(1)
    w.hide()
    w.run(20)  # inside the camera-shift window the whole time
    assert len(w.alerts) == 1


def test_wearable_ignores_memory_photo_rows_and_counts_each_sighting_once(w):
    oid = "wallet_01"
    w.photo(oid, "moved")  # memory rows on a moving camera are not evidence of anything
    w.run(1)
    assert w.state().state == "IDLE"
    w.sight()  # one observation (+ its photo row) -> exactly one episode
    w.run(1)
    assert w.state().evidence == "object_observed"
    assert sum(e["what"] == "pending" for e in w.engine.log) == 1


@pytest.mark.parametrize("status", [{"camera": "error"}, {"camera": "active",
                                     "warning": "The camera is sending black frames."}])
def test_camera_disconnected_or_dark_cancels_pending(db, status):
    w = World(db)
    w.sight()
    w.run(1)
    w.status.clear()
    w.status.update(status)
    w.hide()
    w.run(20)
    assert w.alerts == [] and w.state().state == CANCELLED
    assert w.state().reason in ("camera_unavailable", "camera_dark")


def test_scan_room_cancels_pending(w):
    w.sight()
    w.run(1)
    w.modes.mode = "CALIBRATING"
    w.hide()
    w.run(20)
    assert w.alerts == [] and w.state().reason == "camera_repositioning"


def test_stationary_camera_needs_a_departure_and_grounds_the_place(db):
    feed = DepartureFeed()
    w = World(db, camera_mode="fixed", departures=feed, status={"camera": "active",
                                                                     "target_left_count": 0})
    w.sight(region="Bed", event_type="moved")
    w.run(1)
    assert w.state().evidence == "placement_inferred"
    w.run(30)
    assert w.alerts == []  # still in view, nobody left
    w.status.update(target_left_count=1, target_left_at=w.clock.t)
    w.run(2)
    assert len(w.alerts) == 1 and w.alerts[0]["items"][0]["place"] == "on the bed"


def test_stationary_camera_shift_or_view_change_cancels(db):
    w = World(db, camera_mode="fixed", status={"camera": "active"})
    w.sight(event_type="moved")
    w.run(1)
    w.memory.view_id = "view-b"  # Scan room finished: old region isn't reliable now
    w.run(2)
    assert w.state().reason == "location_unreliable"


# ---------- mode switching, pause, acknowledgement ----------

def test_rapid_mode_switching_cancels_pending_and_queued(w):
    w.sight()
    w.run(1)
    w.engine.update_settings({"mode": "everyday"})
    assert w.state().state == CANCELLED and w.state().reason == "mode_changed"
    w.engine.update_settings({"mode": "high_assistance"})
    w.engine.update_settings({"mode": "off"})
    w.hide()
    w.run(30)
    assert w.alerts == []


def test_pause_and_resume(w):
    w.sight()
    w.run(1)
    w.engine.pause()
    w.hide()
    w.run(30)
    assert w.alerts == [] and w.state().reason == "paused"
    w.engine.resume()
    w.clock.t += 1
    w.sight()
    w.run(1)
    w.hide()
    w.run(20)
    assert len(w.alerts) == 1


def test_have_it_dismisses_and_snooze_reminds_once_more(w):
    w.sight()
    w.run(1)
    w.hide()
    w.run(20)
    w.deliver(w.alerts[0])
    assert w.engine.acknowledge("snooze")["ok"]
    assert w.state().state == PENDING_REMINDER
    w.run(500, step=10)
    assert len(w.alerts) == 1
    w.run(200, step=10)
    assert len(w.alerts) == 2  # after the 10 min snooze
    w.deliver(w.alerts[1])
    assert w.engine.acknowledge("have_it")["ok"] and w.state().reason == "acknowledged"


def test_ack_with_no_reminder_is_harmless(w):
    assert w.engine.acknowledge("have_it") == {"ok": False, "why": "no_recent_reminder"}
    with pytest.raises(ValueError):
        w.engine.acknowledge("explode")


# ---------- delivery ----------

def test_claim_prevents_double_send_and_failures_retry_once(w):
    w.sight()
    w.run(1)
    w.hide()
    w.run(20)
    a = w.alerts[0]
    w.engine.claim(a["id"])
    with pytest.raises(PermissionError):
        w.engine.claim(a["id"])  # second agent / duplicate poll
    assert w.engine.report(a["id"], "failed", "timeout")["status"] == "queued"
    assert w.engine.alerts() == []  # not before the retry delay
    w.clock.t += 21
    assert [x["id"] for x in w.engine.alerts()] == [a["id"]]
    w.engine.claim(a["id"])
    assert w.engine.report(a["id"], "failed", "timeout")["status"] == "failed"
    assert w.state().reason == "delivery_failed"


def test_agent_offline_expires_queued_alert_and_unknown_is_never_resent(w):
    w.sight()
    w.run(1)
    w.hide()
    w.run(20)
    w.run(130, step=10)
    assert w.engine.alerts("expired")[0]["reason"] == "agent offline"
    assert w.state().reason == "delivery_unavailable"
    w.sight("car key")
    w.run(1)
    w.hide("car key")
    w.run(80)
    b = w.alerts[-1]
    w.engine.claim(b["id"])
    w.clock.t += 61
    w.engine.tick()
    assert w.engine.alerts("unknown")[0]["id"] == b["id"]
    assert w.engine.alerts() == []


# ---------- explicit checks (manual demo trigger, "heading out") ----------

def test_manual_check_uses_real_memory_and_is_labelled(w):
    assert w.engine.check()["blocked"] == "no_eligible_items"  # nothing stored yet
    w.sight("wallet")
    w.clock.t += 30
    r = w.engine.check("manual")
    assert r["queued"] and r["alert"]["trigger"] == "manual"
    item = r["alert"]["items"][0]
    assert item["object_id"] == "wallet_01" and item["evidence"] in ("object_observed", "stored_observation")
    assert {s["object_id"]: s["reason"] for s in r["skipped"]} == {"car_key_01": "no_memory"}
    assert w.engine.check("manual")["skipped"][0]["reason"] in ("already_queued", "no_memory")


def test_check_respects_off_pause_and_missing_photos(db):
    w = World(db, enable=False)
    assert w.engine.check()["blocked"] == "reminders_off"
    w.engine.update_settings({"mode": "everyday", "enabled": True}, opt_in=True)
    w.sight(photo=False)
    assert w.engine.check("heading_out")["skipped"][0] == {"object_id": "car_key_01", "reason": "no_memory"}
    assert {"object_id": "wallet_01", "reason": "no_photo"} in w.engine.check("heading_out")["skipped"]
    w.engine.pause()
    assert w.engine.check()["blocked"] == "paused"
    with pytest.raises(ValueError):
        w.engine.check("because")


# ---------- API ----------

@pytest.fixture
def api(tmp_path, monkeypatch):
    save_regions(TEST_AREAS, tmp_path / "regions.json")
    monkeypatch.setenv("CTRLF_CAMERA_ENABLED", "0")
    monkeypatch.setenv("CTRLF_REMINDERS_THREAD", "0")
    monkeypatch.setenv("CTRLF_DB_PATH", str(tmp_path / "api.db"))
    monkeypatch.setenv("CTRLF_SNAPSHOT_DIR", str(tmp_path / "snaps"))
    monkeypatch.setenv("CTRLF_REGIONS", str(tmp_path / "regions.json"))
    import main
    main = importlib.reload(main)
    with TestClient(main.app) as c:
        yield c, main


def test_reminder_api_opt_in_events_check_and_delivery(api):
    c, main = api
    assert c.get("/api/reminders/settings").json()["active"] is False
    assert c.put("/api/reminders/settings", json={"mode": "high_assistance", "enabled": True}).status_code == 403
    assert c.put("/api/reminders/settings", headers=LOCAL,
                 json={"mode": "high_assistance", "enabled": True}).status_code == 409  # no opt-in
    s = c.put("/api/reminders/settings", headers=LOCAL,
              json={"mode": "high_assistance", "enabled": True, "opt_in": True}).json()
    assert s["active"] and s["settings"]["important"] == ["keys", "wallet", "phone"]
    assert c.post("/api/reminders/events", json={}).status_code == 403
    assert c.post("/api/reminders/events", headers=LOCAL, json={"event_type": "x"}).status_code == 422
    r = c.post("/api/reminders/events", headers=LOCAL, json={
        "event_id": "h1", "event_type": "interaction_candidate", "object_id": "wallet",
        "timestamp": "2026-10-17T18:30:00Z", "confidence": 0.7}).json()
    assert r["result"] == "recorded"
    assert c.post("/api/reminders/check", headers=LOCAL, json={}).json()["blocked"] == "no_eligible_items"
    assert c.get("/api/reminders/alerts").json() == []
    assert c.post("/api/reminders/alerts/99/claim", headers=LOCAL).status_code == 404
    assert c.post("/api/reminders/ack", headers=LOCAL, json={"action": "pause"}).json()["paused"]
    assert c.get("/api/reminders/settings").json()["settings"]["paused"] is True


# ---------- Amanda's vision events (backend/events.py contract, observations table) ----------

def test_vision_pickup_then_placement_schedules_and_reminds(db):
    w = World(db, mode="everyday")
    w.sight()
    w.run(1)
    assert w.state().state != PENDING_REMINDER  # Everyday: a sighting alone is not enough
    w.observe(E.INTERACTION_CANDIDATE, conf=0.4)
    w.observe(E.POSSIBLE_PICKUP, conf=0.7)
    w.run(1)
    w.observe(E.PLACEMENT_CONFIRMED, conf=0.75)
    w.run(1)
    o = w.state()
    assert o.state == PENDING_REMINDER and o.evidence == "placement_confirmed" and o.snapshot_id
    w.hide()
    w.run(200, step=5)
    assert len(w.alerts) == 1 and w.alerts[0]["items"][0]["evidence"] == "placement_confirmed"


@pytest.mark.parametrize("conf,evidence", [(0.7, ["hand_near_object", "object_moved_with_hand"]),
                                           (0.55, ["hand_near_object", "object_left_with_hand"])])
def test_vision_pickup_cancels_pending(w, conf, evidence):
    w.sight()
    w.run(1)
    w.observe(E.POSSIBLE_PICKUP, conf=conf, evidence=evidence)
    w.run(1)
    assert w.state().state == CANCELLED and w.state().reason == "picked_up"
    w.hide()
    w.run(30)
    assert w.alerts == []


def test_vision_hand_near_item_never_cancels(w):
    w.sight()
    w.run(1)
    for _ in range(3):
        w.observe(E.INTERACTION_CANDIDATE, conf=0.4)
        w.run(1)
    assert w.state().state == PENDING_REMINDER
    w.hide()
    w.run(20)
    assert len(w.alerts) == 1


def test_vision_placement_waits_for_its_photo(db):
    w = World(db, mode="everyday")
    ev = w.observe(E.PLACEMENT_CONFIRMED, conf=0.8, photo=False)  # photo not written yet
    w.sight(photo=False)
    w.run(1)
    assert w.state().state == PLACEMENT_CANDIDATE
    db.set_observation_snapshot(ev["event_id"], w.photo("wallet_01", E.PLACEMENT_CONFIRMED))
    w.run(1)
    assert w.state().state == PENDING_REMINDER


def test_vision_events_from_before_startup_are_ignored(db):
    w0 = World(db, enable=False)
    w0.observe(E.PLACEMENT_CONFIRMED, conf=0.9)
    w = World(db, mode="everyday")  # engine started after that placement
    w.run(5)
    assert w.state().state == "IDLE"


def test_fixed_camera_uses_memory_moves_and_vision_events_once(db):
    w = World(db, camera_mode="fixed", mode="everyday", status={"camera": "active"})
    w.sight(event_type="moved")
    w.run(1)
    assert w.state().evidence == "placement_inferred"
    w.photo("wallet_01", "first_seen")  # memory's first_seen photo rows aren't events
    w.run(1)
    assert sum(e["what"] == "pending" for e in w.engine.log) == 1
