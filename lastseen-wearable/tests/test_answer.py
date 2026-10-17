import logging
from datetime import datetime

import numpy as np
import pytest

from lastseen.brain.answer import AnswerEngine
from lastseen.bus import Bus
from lastseen.config import load_config
from lastseen.engine.zones import Zone, ZoneMap
from lastseen.memory.store import Store
from lastseen.types import TrackerEvent
from lastseen.vision.identity import Gallery

BOX = (600, 300, 640, 340)
FULL = [(0, 0), (1, 0), (1, 1), (0, 1)]


def T(h, m):
    return datetime(2026, 5, 1, h, m).timestamp()


class Fixture:
    def __init__(self, tmp_path, zones=None, enroll=("airpods", "glasses", "water_bottle"), **kw):
        self.cfg = load_config("config.yaml")
        self.cfg.paths.data = str(tmp_path)
        self.cfg.camera.mode = "fixed"
        self.bus = Bus()
        self.q = self.bus.subscribe()
        self.db = str(tmp_path / "db.sqlite")
        self.store = Store(self.db, self.bus)
        self.zones = zones if zones is not None else ZoneMap([Zone("desk", "surface", FULL)])
        for i in enroll:
            g = Gallery(i, tmp_path / "gallery")
            g.add_pos(np.ones((1, 512), np.float32))
            g.save()
        self.eng = AnswerEngine(self.cfg, self.store, self.zones, bus=self.bus, **kw)

    def row(self, item="airpods", state="PLACED", zone="desk", conf=0.9, ts=T(15, 42), bbox=BOX):
        name = next(i.display_name for i in self.cfg.items if i.id == item)
        self.store.upsert_item(item, name, False, state, zone, bbox, conf, ts)

    def ev(self, kind, ts, item="airpods", conf=0.9, bbox=BOX, snap=None, clip=None, to_zone="desk"):
        return self.store.add_event(TrackerEvent(kind, item, ts, None, to_zone, bbox, conf), snap, clip)

    def msgs(self):
        out = []
        while not self.q.empty():
            out.append(self.q.get_nowait())
        return out


@pytest.fixture
def fx(tmp_path):
    return Fixture(tmp_path)


def test_placed_plural(fx):
    fx.row(); fx.ev("PLACED", T(15, 42))
    r = fx.eng.ask("where are my airpods", "dashboard")
    assert r["text"] == "Your AirPods are on the desk. You put them there at 3:42 PM."
    assert r["item_id"] == "airpods" and r["state"] == "PLACED" and r["zone"] == "desk"
    assert r["uncertain"] is False and r["ts_placed"] == T(15, 42)
    assert r["display_name"] == "AirPods"


def test_placed_singular_in_the_room(tmp_path):
    f = Fixture(tmp_path, zones=ZoneMap([]))
    f.row("water_bottle", ts=T(9, 5)); f.ev("PLACED", T(9, 5), "water_bottle")
    assert f.eng.ask("where is my water bottle", "x")["text"] == \
        "Your water bottle is in the room. You put it there at 9:05 AM."
    assert f.eng.ask("where is my water bottle", "x")["display_name"] == "water bottle"


def test_seen_event_used(fx):
    fx.row(); fx.ev("PLACED", T(15, 0)); fx.ev("SEEN", T(16, 10))
    assert "at 4:10 PM." in fx.eng.ask("where are my airpods", "x")["text"]


def test_held(fx):
    fx.row(state="HELD")
    assert fx.eng.ask("where are my airpods", "x")["text"] == "You're holding them right now."
    fx.row("water_bottle", state="HELD")
    assert fx.eng.ask("where is my water bottle", "x")["text"] == "You're holding it right now."


def test_hidden(fx):
    fx.zones.zones = [Zone("bed", "cover", FULL)]
    fx.row(state="HIDDEN", zone="bed"); fx.ev("HIDDEN", T(14, 3), to_zone="bed")
    assert fx.eng.ask("where are my airpods", "x")["text"] == (
        "I last saw your AirPods going under the blanket on the bed at 2:03 PM. They're probably still there.")
    fx.row("water_bottle", state="HIDDEN", zone="bed"); fx.ev("HIDDEN", T(14, 3), "water_bottle")
    assert fx.eng.ask("where is my water bottle", "x")["text"].endswith("It's probably still there.")


def test_carried_out(fx):
    fx.row(state="CARRIED_OUT"); fx.ev("PLACED", T(8, 0)); fx.ev("CARRIED_OUT", T(17, 30))
    assert fx.eng.ask("where are my airpods", "x")["text"] == \
        "You picked up your AirPods at 5:30 PM and took them out of view."
    fx.row("water_bottle", state="CARRIED_OUT"); fx.ev("CARRIED_OUT", T(17, 31), "water_bottle")
    assert fx.eng.ask("where is my water bottle", "x")["text"].endswith("and took it out of view.")


def test_unknown_with_past_placed(fx):
    fx.row(state="UNKNOWN", zone=None); fx.ev("PLACED", T(10, 15))
    assert fx.eng.ask("where are my airpods", "x")["text"] == (
        "I can't see your AirPods right now. I last saw them on the desk at 10:15 AM.")
    fx.row("water_bottle", state="UNKNOWN", zone=None); fx.ev("PLACED", T(10, 15), "water_bottle")
    assert "I last saw it on the desk" in fx.eng.ask("where is my water bottle", "x")["text"]


def test_enrolled_no_events(fx):
    fx.row(state="UNKNOWN", zone=None, bbox=None, ts=None)
    assert fx.eng.ask("where are my airpods", "x")["text"] == \
        "I haven't seen your AirPods since you showed them to me."
    assert fx.eng.ask("where is my water bottle", "x")["text"] == \
        "I haven't seen your water bottle since you showed it to me."


def test_not_enrolled(tmp_path):
    f = Fixture(tmp_path, enroll=())
    r = f.eng.ask("where are my glasses", "voice")
    assert r["text"] == "I haven't been shown your glasses yet."
    assert r["item_id"] == "glasses"


def test_unknown_item_no_crash(fx):
    r = fx.eng.ask("where's my passport", "voice")
    assert r["item_id"] is None and r["text"] == "I'm not tracking anything called passport yet."
    assert r["display_name"] is None
    assert [m["type"] for m in fx.msgs()] == ["show_answer"]


def test_intent_none_logged_not_published(fx):
    r = fx.eng.ask("what a lovely day", "voice")
    assert r["text"] == "Sorry, I didn't catch which of your things you mean." and r["item_id"] is None
    assert fx.store.recent_asks(1)[0]["answer"] == r["text"]
    assert fx.msgs() == []


def test_uncertain_prefix(fx):
    fx.row(conf=0.5); fx.ev("PLACED", T(15, 42), conf=0.5)
    r = fx.eng.ask("where are my airpods", "x")
    assert r["text"] == "I think your AirPods are on the desk. You put them there at 3:42 PM."
    assert r["uncertain"] is True
    fx.row(state="HELD", conf=0.5)
    assert fx.eng.ask("where are my airpods", "x")["text"] == "I think you're holding them right now."


def test_uncertain_uses_deciding_event_not_older(fx):
    fx.row(); fx.ev("PLACED", T(15, 0), conf=0.4); fx.ev("PLACED", T(15, 42), conf=0.9)
    assert not fx.eng.ask("where are my airpods", "x")["uncertain"]


def test_held_time(fx):
    fx.row()
    assert fx.eng.ask("when did I last have my airpods", "x")["text"] == \
        "I haven't seen you pick up your AirPods."
    fx.ev("PICKED_UP", T(13, 7))
    assert fx.eng.ask("when did I last have my airpods", "x")["text"] == \
        "You last picked up your AirPods at 1:07 PM."


def test_enroll_intent(tmp_path):
    calls = []
    f = Fixture(tmp_path, enroll_fn=lambda i, n: calls.append((i, n)) or {"ok": True})
    r = f.eng.ask("enroll my glasses", "x")
    assert calls == [("glasses", "glasses")]
    assert r["text"] == "OK, pick it up and put it down where I can see it."
    g = Fixture(tmp_path / "b")
    assert g.eng.ask("enroll my glasses", "x")["text"] == "I can't learn new things right now."


def test_urls_and_ts(fx):
    fx.row()
    fx.ev("PLACED", T(15, 0), snap="/a/old.jpg", clip="/a/old.mp4")
    fx.ev("SEEN", T(15, 42), snap="/a/new.jpg")
    fx.ev("PICKED_UP", T(15, 50))
    r = fx.eng.ask("where are my airpods", "x")
    assert r["snapshot_url"] == "/clips/new.jpg" and r["clip_url"] is None
    fx.row("glasses", ts=None)
    r = fx.eng.ask("where are my glasses", "x")
    assert r["snapshot_url"] is None and r["ts_placed"] is None


def test_logged_and_published(fx):
    fx.row(); fx.ev("PLACED", T(15, 42))
    fx.msgs()
    r = fx.eng.ask("where are my airpods", "dashboard")
    a = fx.store.recent_asks(1)[0]
    assert (a["source"], a["question"], a["item_id"], a["answer"], a["state"], a["zone"]) == (
        "dashboard", "where are my airpods", "airpods", r["text"], "PLACED", "desk")
    assert a["latency_ms"] == r["latency_ms"]
    m = fx.msgs()
    assert len(m) == 1 and m[0]["type"] == "show_answer" and m[0]["answer"] == r


def test_never_raises(fx, caplog):
    fx.store.get_item = lambda *_: 1 / 0
    with caplog.at_level(logging.ERROR):
        r = fx.eng.ask("where are my airpods", "x")
    assert r["text"] == "Sorry, something went wrong — try asking again." and r["item_id"] is None
    assert "answer failed" in caplog.text
    assert fx.store.recent_asks(1)[0]["answer"] == r["text"]


def test_frame_wh_used_and_fallback(tmp_path):
    zones = ZoneMap([Zone("desk", "surface", [(0, 0), (0.5, 0), (0.5, 1), (0, 1)])])
    f = Fixture(tmp_path, zones=zones, frame_wh=lambda: (2000, 1000))
    f.row(bbox=(1800, 300, 1900, 400)); f.ev("PLACED", T(15, 42))
    assert "in the room" in f.eng.ask("where are my airpods", "x")["text"]   # x=1150 > 1000
    f2 = Fixture(tmp_path / "n", zones=zones, frame_wh=lambda: None)         # falls back to 1280x720
    f2.row(bbox=(100, 300, 200, 400)); f2.ev("PLACED", T(15, 42))
    assert "on the desk" in f2.eng.ask("where are my airpods", "x")["text"]


def test_restart_same_answer(tmp_path):
    f = Fixture(tmp_path)
    f.row(); f.ev("PLACED", T(15, 42))
    q = "where are my airpods"
    a1 = f.eng.ask(q, "x")["text"]
    e2 = AnswerEngine(f.cfg, Store(f.db, Bus()), f.zones)
    assert e2.ask(q, "x")["text"] == a1


class FakeLLM:
    def __init__(self, item=None, reword=None, boom=False):
        self.item, self.rw, self.boom = item, reword, boom
        self.calls = []

    def parse_item(self, q, items, timeout_s=None):
        self.calls.append(("parse", q))
        if self.boom:
            raise RuntimeError("down")
        return self.item

    def reword(self, text, facts, timeout_s=None):
        self.calls.append(("reword", text, facts))
        if self.boom:
            raise RuntimeError("down")
        return self.rw


def test_llm_parse_and_reword(tmp_path):
    llm = FakeLLM(item="airpods", reword="Your AirPods are on the desk, since 3:42.")
    f = Fixture(tmp_path, llm=llm)
    f.row(); f.ev("PLACED", T(15, 42))
    r = f.eng.ask("do you know the whereabouts of my little earbud thing", "x")
    assert r["item_id"] == "airpods" and r["text"] == "Your AirPods are on the desk, since 3:42."
    reword = [c for c in llm.calls if c[0] == "reword"][0]
    assert reword[1].startswith("Your AirPods are on the desk.") and reword[2]["state"] == "PLACED"


def test_llm_not_consulted_when_regex_resolves(tmp_path):
    llm = FakeLLM(item="glasses")
    f = Fixture(tmp_path, llm=llm)
    f.row(); f.ev("PLACED", T(15, 42))
    assert f.eng.ask("where are my airpods", "x")["item_id"] == "airpods"
    assert not [c for c in llm.calls if c[0] == "parse"]


def test_llm_failure_keeps_template(tmp_path):
    f = Fixture(tmp_path, llm=FakeLLM(boom=True))
    f.row(); f.ev("PLACED", T(15, 42))
    assert f.eng.ask("where are my airpods", "x")["text"].startswith("Your AirPods are on the desk.")
    assert f.eng.ask("blorp", "x")["item_id"] is None


def test_llm_skipped_when_flag_off(tmp_path):
    llm = FakeLLM(item="airpods", reword="REWORDED")
    f = Fixture(tmp_path, llm=llm)
    f.cfg.features.chalk_llm = False
    f.row(); f.ev("PLACED", T(15, 42))
    assert f.eng.ask("where are my airpods", "x")["text"].startswith("Your AirPods")
    assert f.eng.ask("whereabouts of the earbud thing", "x")["item_id"] is None
    assert llm.calls == []


# ------------------------------------------------------------------ wearable mode
def _wear(f):
    f.cfg.camera.mode = "wearable"
    f.cfg.features.chalk_llm = False
    return f


def test_fmt_ago():
    from lastseen.brain.answer import fmt_ago, fmt_time
    now = T(12, 0)
    assert fmt_ago(now - 20, now) == "just now"
    assert fmt_ago(now - 60, now) == "1 minute ago"
    assert fmt_ago(now - 180, now) == "3 minutes ago"
    assert fmt_ago(now - 7200, now) == "at " + fmt_time(now - 7200)


def test_wearable_placed_answer(tmp_path):
    import time
    f = _wear(Fixture(tmp_path))
    ts = time.time() - 120
    f.row(ts=ts); f.ev("PLACED", ts)
    assert f.eng.ask("where are my airpods", "x")["text"] == \
        "You put your AirPods down 2 minutes ago. I put a photo of where on the screen."


def test_wearable_untouched_answer(tmp_path):
    f = _wear(Fixture(tmp_path))
    f.row(state="UNKNOWN", zone=None); f.ev("PLACED", T(10, 0))
    assert f.eng.ask("where are my airpods", "x")["text"] == \
        "Sorry, I did not see you interact with your AirPods."


def test_wearable_disabled_item_answer(tmp_path):
    f = _wear(Fixture(tmp_path))
    next(i for i in f.cfg.items if i.id == "keys").enabled = False
    r = f.eng.ask("where are my keys", "x")
    assert r["text"] == "Sorry, I did not see you interact with your keys."


def test_wearable_with_you_answer(tmp_path):
    from lastseen.brain.answer import fmt_time
    f = _wear(Fixture(tmp_path))
    f.row(state="CARRIED_OUT"); f.ev("CARRIED_OUT", T(17, 30))
    assert f.eng.ask("where are my airpods", "x")["text"] == \
        f"You picked up your AirPods at {fmt_time(T(17, 30))} and had them with you."


def test_answer_item_logs_and_publishes(tmp_path):
    import time
    f = _wear(Fixture(tmp_path))
    f.row(ts=time.time()); f.ev("PLACED", time.time())
    f.msgs()
    r = f.eng.answer_item("airpods", "proactive")
    a = f.store.recent_asks(1)[0]
    assert a["source"] == "proactive" and a["question"] == "[proactive] airpods"
    assert r["item_id"] == "airpods"
    assert [m["type"] for m in f.msgs()] == ["show_answer"]


def test_wearable_placed_uses_placed_not_seen_time(tmp_path):
    import time
    f = _wear(Fixture(tmp_path))
    now = time.time()
    f.row(ts=now - 30); f.ev("PLACED", now - 300); f.ev("SEEN", now - 30)
    assert f.eng.ask("where are my airpods", "x")["text"] == \
        "You put your AirPods down 5 minutes ago. I put a photo of where on the screen."


def test_wearable_unknown_has_no_stale_snapshot(tmp_path):
    f = _wear(Fixture(tmp_path))
    f.row(state="UNKNOWN", zone=None); f.ev("SEEN", T(10, 0), snap="/a/old.jpg", clip="/a/old.mp4")
    r = f.eng.ask("where are my airpods", "x")
    assert r["snapshot_url"] is None and r["clip_url"] is None


def test_wearable_disabled_has_no_stale_snapshot(tmp_path):
    f = _wear(Fixture(tmp_path))
    next(i for i in f.cfg.items if i.id == "glasses").enabled = False
    f.row("glasses"); f.ev("PLACED", T(10, 0), "glasses", snap="/a/old.jpg")
    r = f.eng.ask("where are my glasses", "x")
    assert r["text"].startswith("Sorry, I did not see") and r["snapshot_url"] is None


def test_wearable_with_you_has_no_snapshot(tmp_path):
    f = _wear(Fixture(tmp_path))
    f.row(state="CARRIED_OUT"); f.ev("SEEN", T(17, 0), snap="/a/gone.jpg"); f.ev("CARRIED_OUT", T(17, 30))
    r = f.eng.ask("where are my airpods", "x")
    assert r["snapshot_url"] is None and r["clip_url"] is None


def test_wearable_placed_snapshot_only_from_current_placement(tmp_path):
    import time
    f = _wear(Fixture(tmp_path))
    now = time.time()
    f.ev("SEEN", now - 600, snap="/a/old.jpg")
    f.row(ts=now - 60); f.ev("PLACED", now - 60)
    assert f.eng.ask("where are my airpods", "x")["snapshot_url"] is None
    f.ev("SEEN", now - 30, snap="/a/new.jpg")
    assert f.eng.ask("where are my airpods", "x")["snapshot_url"].endswith("new.jpg")


def test_wearable_placed_skips_reword(tmp_path):
    import time
    llm = FakeLLM(reword="REWORDED")
    f = _wear(Fixture(tmp_path, llm=llm))
    f.cfg.features.chalk_llm = True
    f.row(ts=time.time() - 120); f.ev("PLACED", time.time() - 120)
    r = f.eng.ask("where are my airpods", "x")
    assert r["text"].endswith("I put a photo of where on the screen.")
    assert not [c for c in llm.calls if c[0] == "reword"]


def test_proactive_uses_voice_reword_budget(tmp_path, monkeypatch):
    from lastseen.brain import answer as ans
    seen = []

    class LLM(FakeLLM):
        def reword(self, text, facts, timeout_s=None):
            seen.append(timeout_s)
            return None

    f = Fixture(tmp_path, llm=LLM())
    f.row(); f.ev("PLACED", T(15, 42))
    f.eng.answer_item("airpods", "proactive")
    assert seen and seen[0] <= ans.VOICE_REWORD_S
