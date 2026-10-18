"""Entry-point helpers that can be tested without models."""
import json
import logging

from lastseen import __main__ as entry
from lastseen.config import Config, FeaturesCfg


def _cfg(**features):
    return Config(items=[], features=FeaturesCfg(**features), device="cpu")


def test_people_tracker_failure_gives_none(caplog):
    def boom(*a, **kw):
        raise RuntimeError("no yolo26n.pt")

    with caplog.at_level(logging.ERROR):
        assert entry._make_people(_cfg(), factory=boom) is None
    assert any("people tracker" in m for m in caplog.messages)


def test_people_tracker_off_is_not_built():
    calls = []
    assert entry._make_people(_cfg(people_tracking=False), factory=lambda *a: calls.append(a)) is None
    assert calls == []


def test_people_tracker_built_when_on():
    sentinel = object()
    assert entry._make_people(_cfg(), factory=lambda persons, device: sentinel) is sentinel


def test_jsonl_handler_keeps_traceback(tmp_path):
    path = tmp_path / "s.jsonl"
    h = entry.JsonlHandler(path)
    lg = logging.getLogger("test.jsonl")
    lg.addHandler(h)
    lg.propagate = False
    try:
        try:
            raise ValueError("kaboom")
        except ValueError:
            lg.exception("it failed")
        lg.error("plain")
    finally:
        lg.removeHandler(h)
        h.close()
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert rows[0]["msg"] == "it failed"
    assert "Traceback" in rows[0]["exc"] and "ValueError: kaboom" in rows[0]["exc"]
    assert "exc" not in rows[1]


def test_session_log_survives_uvicorn_setup(tmp_path):
    """uvicorn's default log_config runs dictConfig, which closes every existing handler — the
    session log must keep working after the server config is built."""
    import json
    import logging
    from lastseen.__main__ import JsonlHandler, server_config, setup_logging

    root = logging.getLogger()
    before = list(root.handlers)
    path = setup_logging(str(tmp_path))
    try:
        server_config(object(), 0)
        logging.getLogger("lastseen.test").info("still logging")
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        assert any(r["msg"] == "still logging" for r in rows)
    finally:
        for h in list(root.handlers):
            if h not in before:
                root.removeHandler(h)
                h.close()


def test_faster_whisper_chatter_silenced(tmp_path):
    import logging
    from lastseen.__main__ import setup_logging

    root = logging.getLogger()
    before = list(root.handlers)
    setup_logging(str(tmp_path))
    try:
        assert logging.getLogger("faster_whisper").getEffectiveLevel() >= logging.WARNING
    finally:
        for h in list(root.handlers):
            if h not in before:
                root.removeHandler(h)
                h.close()


def _patch_heavy(monkeypatch, calls):
    import lastseen.engine.touch as touch_m
    import lastseen.engine.vision_loop as vl_m
    import lastseen.vision.change as change_m
    import lastseen.vision.classify as cls_m
    import lastseen.vision.detector as det_m
    import lastseen.vision.embedder as emb_m
    import lastseen.vision.hands as hands_m
    import lastseen.vision.identity as id_m

    class Det:
        def __init__(self, cfg):
            pass

        def set_items(self, items):
            calls["set_items"] = list(items)

    class Rec:
        def __init__(self, name):
            self.name = name

        def __call__(self, *a, **kw):
            calls.setdefault("built", []).append(self.name)
            return object()

    class Loop:
        def __init__(self, *a, **kw):
            calls["loop"] = (a, kw)

    monkeypatch.setattr(det_m, "Detector", Det)
    monkeypatch.setattr(emb_m, "ClipEmbedder", Rec("embedder"))
    monkeypatch.setattr(hands_m, "HandDetector", Rec("hands"))
    monkeypatch.setattr(change_m, "ChangeDetector", Rec("change"))
    monkeypatch.setattr(cls_m, "ItemClassifier", Rec("classifier"))
    monkeypatch.setattr(touch_m, "TouchWatcher", Rec("touch"))
    monkeypatch.setattr(id_m, "Identity", Rec("identity"))
    monkeypatch.setattr(vl_m, "VisionLoop", Loop)
    monkeypatch.setattr(entry, "_make_people", lambda cfg, factory=None: calls.setdefault("people", True))


def test_wearable_build_skips_people(monkeypatch, tmp_path):
    from lastseen.config import CameraCfg

    calls = {}
    _patch_heavy(monkeypatch, calls)
    cfg = Config(items=[], features=FeaturesCfg(), device="cpu", camera=CameraCfg(mode="wearable"))
    loop, hands = entry._build_vision(cfg, object(), object(), object())
    assert "people" not in calls
    assert "classifier" not in calls.get("built", []) and "touch" not in calls.get("built", [])
    assert calls["set_items"] == []
    a, kw = calls["loop"]
    assert kw["people"] is None and kw["classifier"] is None and kw["touch"] is None


def test_fixed_build_keeps_people_and_touch(monkeypatch):
    calls = {}
    _patch_heavy(monkeypatch, calls)
    entry._build_vision(_cfg(), object(), object(), object())
    assert calls["people"] is True
    assert {"classifier", "touch"} <= set(calls["built"])


class _Speaker:
    import threading as _t
    speaking = _t.Event()

    def say(self, text):
        pass

    def muted_until(self):
        return 0.0


class _Engine:
    def answer_item(self, item_id, source):
        return {"text": ""}


class _Ctx:
    dismiss_fn = None


def _asker_cfg(mode):
    from lastseen.config import CameraCfg, ItemCfg

    items = [ItemCfg(id="airpods", display_name="AirPods", synonyms=["airpods"]),
             ItemCfg(id="keys", display_name="keys", synonyms=["keys"], enabled=False)]
    return Config(items=items, features=FeaturesCfg(lost_sight_ask=True), device="cpu",
                  camera=CameraCfg(mode=mode))


def test_asker_not_started_in_fixed_mode():
    import threading

    ctx = _Ctx()
    dialog, th = entry._start_asker(_asker_cfg("fixed"), object(), _Speaker(), _Engine(), object(),
                                    threading.Event(), ctx)
    assert dialog is None and th is None and ctx.dismiss_fn is None


def test_asker_started_in_wearable_mode_with_all_items():
    import threading

    class Loop:
        def wear_status(self):
            return [], True

    from lastseen.bus import Bus

    ctx = _Ctx()
    stop = threading.Event()
    dialog, th = entry._start_asker(_asker_cfg("wearable"), Loop(), _Speaker(), _Engine(), Bus(), stop, ctx)
    try:
        assert dialog is not None and th is not None and ctx.dismiss_fn is not None
        assert [i.id for i in dialog.items] == ["airpods", "keys"]
    finally:
        stop.set()
        th.join(2)
