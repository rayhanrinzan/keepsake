import threading
import time

from lastseen.bus import Bus
from lastseen.config import ItemCfg, WearableCfg
from lastseen.engine.wear_tracker import WearStatus
from lastseen.proactive.lost_sight import LostSightAsker, parse_reply, run_asker

ITEMS = [
    ItemCfg(id="airpods", display_name="AirPods", synonyms=["airpods", "earbuds"]),
    ItemCfg(id="keys", display_name="keys", synonyms=["keys"]),
    ItemCfg(id="wallet", display_name="wallet", synonyms=["wallet"]),
]


def st(id, phase="PLACED_GONE", unseen=0.0, sightings=0):
    return WearStatus(id, {"airpods": "AirPods", "keys": "keys"}[id], phase, unseen, None, sightings)


class Rig:
    def __init__(self):
        self.t = 0.0
        self.said = []
        self.speaking = False
        self.asker = LostSightAsker(
            WearableCfg(), ITEMS, self.said.append, lambda: self.speaking,
            lambda i, s: {"text": f"ANS {i}"}, clock=lambda: self.t)

    def tick(self, *sts, fresh=True):
        self.asker.tick(list(sts), fresh)


def test_parse_reply():
    assert parse_reply("yes") == "yes"
    assert parse_reply("yeah where") == "yes"
    assert parse_reply("no") == "no"
    assert parse_reply("nope") == "no"
    assert parse_reply("yeah I know where it is") == "no"
    assert parse_reply("I'm fine") == "no"
    assert parse_reply("know") is None
    assert parse_reply("hmm") is None
    assert parse_reply("I'm not sure") == "no"


def test_single_question_at_30s():
    r = Rig()
    r.tick(st("airpods", unseen=29.9))
    assert r.said == []
    r.tick(st("airpods", unseen=30.0))
    assert r.said == ["Are you looking for your AirPods?"]


def test_group_when_due_within_10s():
    r = Rig()
    r.tick(st("airpods", unseen=30.0), st("keys", unseen=21.0))
    assert r.said == ["Are you looking for something?"]


def test_no_group_when_15s_apart():
    r = Rig()
    r.tick(st("airpods", unseen=30.0), st("keys", unseen=15.0))
    assert r.said == ["Are you looking for your AirPods?"]
    r.t = 0.5
    r.tick(st("airpods", unseen=30.5), st("keys", unseen=15.5))   # deadline = 8.5
    r.t = 9.0
    r.tick(st("airpods", unseen=39.0), st("keys", unseen=24.0))   # deadline passes, closes
    r.t = 15.0
    r.tick(st("airpods", unseen=45.0), st("keys", unseen=30.0))
    assert r.said[-1] == "Are you looking for your keys?"


def test_not_asked_when_with_you_or_untracked():
    r = Rig()
    r.tick(st("airpods", "WITH_YOU", 100), st("keys", "UNTRACKED", 100))
    r.tick(st("airpods", "PLACED_VISIBLE", 100))
    assert r.said == []


def test_no_ask_when_not_fresh():
    r = Rig()
    r.tick(st("airpods", unseen=45.0), fresh=False)
    assert r.said == []


def test_reply_window_starts_after_speech():
    r = Rig()
    r.tick(st("airpods", unseen=30.0))
    r.speaking = True
    r.t = 5.0
    r.tick(st("airpods", unseen=35.0))
    r.speaking = False
    r.t = 5.1
    r.tick(st("airpods", unseen=35.1))          # deadline = 13.1
    r.t = 13.0
    r.tick(st("airpods", unseen=43.0))
    assert r.asker.view()["airpods"]["asking"]
    r.t = 13.2
    r.tick(st("airpods", unseen=43.2))
    assert not r.asker.view()["airpods"]["asking"]
    assert r.asker.view()["airpods"]["unseen_s"] == 0.0
    r.t = 40.0
    r.tick(st("airpods", unseen=70.0))          # effective 26.8 -> no re-ask
    assert len(r.said) == 1
    r.tick(st("airpods", unseen=73.5))
    assert len(r.said) == 2


def _open_single(r):
    r.tick(st("airpods", unseen=30.0))


def test_yes_answers_single():
    r = Rig()
    _open_single(r)
    assert r.asker.on_text("yes") is True
    assert r.said[-1] == "ANS airpods"


def test_no_silences_until_seen_again():
    r = Rig()
    _open_single(r)
    assert r.asker.on_text("no") is True
    r.tick(st("airpods", unseen=200.0))
    assert len(r.said) == 1
    assert r.asker.view()["airpods"]["silenced"]
    r.tick(st("airpods", "PLACED_VISIBLE", 0.0, sightings=1))
    r.tick(st("airpods", unseen=30.0, sightings=1))
    assert len(r.said) == 2


def _open_group(r):
    r.tick(st("airpods", unseen=30.0), st("keys", unseen=25.0))


def test_group_yes_then_item():
    r = Rig()
    _open_group(r)
    assert r.asker.on_text("yes") is True
    assert r.said[-1] == "OK, what item are you looking for?"
    assert r.asker.on_text("my keys") is True
    assert r.said[-1] == "ANS keys"
    assert not r.asker.view()["keys"]["asking"]


def test_group_yes_then_gibberish():
    r = Rig()
    _open_group(r)
    r.asker.on_text("yes")
    assert r.asker.on_text("banana") is True
    assert r.said[-1] == "Sorry, I didn't catch that."


def test_find_question_during_window():
    r = Rig()
    _open_group(r)
    assert r.asker.on_text("where are my keys") is True
    assert r.said[-1] == "ANS keys"
    assert not r.asker.view()["airpods"]["asking"]


def test_dismiss_during_group():
    r = Rig()
    _open_group(r)
    assert r.asker.dismiss("airpods") is True
    assert r.asker.view()["keys"]["asking"] and not r.asker.view()["airpods"]["asking"]
    assert r.asker.dismiss("keys") is True
    assert not r.asker.view()["keys"]["asking"]


def test_dismiss_unknown_item():
    r = Rig()
    r.tick(st("airpods", unseen=1.0))
    assert r.asker.dismiss("nope") is False


def test_text_without_dialog_not_consumed():
    r = Rig()
    assert r.asker.on_text("yes") is False


def test_run_asker_publishes_wear_status():
    class FakeLoop:
        def wear_status(self):
            return [st("airpods", unseen=5.0)], True

    r = Rig()
    bus = Bus()
    q = bus.subscribe()
    stop = threading.Event()
    th = threading.Thread(target=run_asker, args=(r.asker, FakeLoop(), bus, stop, 0.01))
    th.start()
    time.sleep(0.15)
    stop.set()
    th.join(2)
    assert not th.is_alive()
    msgs = []
    while not q.empty():
        msgs.append(q.get())
    ws = [m for m in msgs if m["type"] == "wear_status"]
    assert ws
    assert ws[0]["camera_lost"] is False
    assert ws[0]["config_ids"] == ["airpods", "keys", "wallet"]
    it = ws[0]["items"][0]
    assert set(it) == {"id", "display_name", "phase", "unseen_s", "last_seen_ts", "silenced", "asking"}
    assert it["id"] == "airpods"


def test_silence_cleared_by_pickup_cycle():
    r = Rig()
    _open_single(r)
    r.asker.on_text("no")
    for ph in ("HELD", "PLACED_VISIBLE"):
        r.tick(st("airpods", ph, 0.0))
    r.tick(st("airpods", unseen=30.0))
    assert len(r.said) == 2


def test_timeout_baseline_cleared_by_pickup():
    r = Rig()
    _open_single(r)
    r.tick(st("airpods", unseen=30.5))
    r.t = 9.0
    r.tick(st("airpods", unseen=38.0))      # closes, baseline 38
    r.tick(st("airpods", "HELD", 0.0))
    r.tick(st("airpods", unseen=30.0))
    assert len(r.said) == 2


def test_hard_cap_closes_dialog_while_speaking():
    r = Rig()
    _open_single(r)
    r.speaking = True
    r.t = 37.0
    r.tick(st("airpods", unseen=67.0))
    assert r.asker.view()["airpods"]["asking"]
    r.t = 38.5
    r.tick(st("airpods", unseen=68.5))
    assert not r.asker.view()["airpods"]["asking"]


def test_which_stage_no_closes_quietly():
    r = Rig()
    _open_group(r)
    r.asker.on_text("yes")
    n = len(r.said)
    assert r.asker.on_text("no") is True
    assert len(r.said) == n
    assert not r.asker.view()["keys"]["asking"]


def test_which_stage_natural_phrases():
    for phrase, expect in [("I'm looking for my keys", "ANS keys"), ("um my wallet I think", "ANS wallet"),
                           ("banana", "Sorry, I didn't catch that.")]:
        r = Rig()
        _open_group(r)
        r.asker.on_text("yes")
        assert r.asker.on_text(phrase) is True
        assert r.said[-1] == expect


def test_no_reask_after_single_yes():
    r = Rig()
    _open_single(r)
    r.asker.on_text("yes")
    n = len(r.said)
    r.t = 1.0
    r.tick(st("airpods", unseen=31.0))
    assert len(r.said) == n
    r.t = 30.0
    r.tick(st("airpods", unseen=59.9))
    assert len(r.said) == n
    r.tick(st("airpods", unseen=60.0))
    assert r.said[-1] == "Are you looking for your AirPods?"


def test_no_reask_after_find_question():
    r = Rig()
    _open_group(r)
    r.asker.on_text("where are my keys")
    n = len(r.said)
    r.t = 1.0
    r.tick(st("airpods", unseen=31.0), st("keys", unseen=26.0))
    assert len(r.said) == n
    r.tick(st("airpods", unseen=60.0), st("keys", unseen=55.0))
    assert len(r.said) == n + 1


def test_no_reask_after_which_answer():
    r = Rig()
    _open_group(r)
    r.asker.on_text("yes")
    r.asker.on_text("my keys")
    n = len(r.said)
    r.t = 1.0
    r.tick(st("airpods", unseen=31.0), st("keys", unseen=26.0))
    assert len(r.said) == n
    r.tick(st("airpods", unseen=60.0), st("keys", unseen=55.0))
    assert len(r.said) == n + 1


def test_which_stage_recognises_disabled_item():
    items = [ItemCfg(id="airpods", display_name="AirPods", synonyms=["airpods"]),
             ItemCfg(id="keys", display_name="keys", synonyms=["keys"], enabled=False),
             ItemCfg(id="wallet", display_name="wallet", synonyms=["wallet"])]
    said, asked = [], []
    a = LostSightAsker(WearableCfg(), items, said.append, lambda: False,
                       lambda i, s: asked.append(i) or {"text": f"ANS {i}"}, clock=lambda: 0.0)
    a.tick([st("airpods", unseen=30.0), WearStatus("wallet", "wallet", "PLACED_GONE", 25.0, None, 0)], True)
    a.on_text("yes")
    a.on_text("my keys")
    assert asked == ["keys"]
    assert "keys" not in a.view()       # never asked about: it has no status
