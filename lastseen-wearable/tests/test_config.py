import pytest
from pydantic import ValidationError

from lastseen.config import Config, ItemCfg, load_config


def test_loads_airpods_item(tmp_path):
    cfg = load_config("config.yaml")
    a = next(i for i in cfg.items if i.id == "airpods")
    assert "earbuds" in a.synonyms and a.critical is False
    assert [i.id for i in cfg.items] == ["airpods", "water_bottle", "wallet", "keys", "glasses"]
    assert cfg.features.clips is True and cfg.features.touch_to_track is False


def test_repo_config_is_wearable():
    cfg = load_config("config.yaml")
    assert cfg.camera.mode == "wearable"
    assert [i.id for i in cfg.items] == ["airpods", "water_bottle", "wallet", "keys", "glasses"]
    assert [i.id for i in cfg.enabled_items()] == ["airpods"]
    assert cfg.wearable.ask_after_s == 10 and cfg.wearable.group_window_s == 5
    assert cfg.wearable.reply_window_s == 8 and cfg.wearable.seen_again_hits == 3
    assert cfg.features.lost_sight_ask is True
    assert cfg.features.touch_to_track is False and cfg.features.people_tracking is False


def test_mode_defaults_to_fixed():
    assert Config(items=[ItemCfg(id="a", display_name="A")], device="cpu").camera.mode == "fixed"


def test_wearable_defaults(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("items: []")
    w = load_config(p).wearable
    assert w.ask_after_s == 30 and w.group_window_s == 10 and w.reply_window_s == 8
    assert w.touch_s == 0.5 and w.seen_again_hits == 3 and w.seen_again_window_s == 1.0
    assert w.stale_frame_s == 1.0 and w.best_frame_window_s == 5.0


def test_enabled_items_defaults_to_true_and_keeps_order(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("items:\n  - {id: a, display_name: A}\n"
                 "  - {id: b, display_name: B, enabled: false}\n  - {id: c, display_name: C}")
    cfg = load_config(p)
    assert [i.id for i in cfg.enabled_items()] == ["a", "c"]


def test_defaults():
    cfg = load_config("config.yaml")
    assert cfg.detector.every_n == 3 and cfg.engine.uncertain_conf == 0.6
    assert cfg.identity.sim_thresh == 0.70 and cfg.detector.conf == 0.001 and cfg.device in ("mps", "cuda", "cpu")


def test_bad_value_rejected(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("camera: {fps_target: -1}\nitems: []")
    with pytest.raises(ValidationError):
        load_config(p)


def test_server_defaults(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("items: []")
    cfg = load_config(p)
    assert cfg.server.lan_dashboard is False and cfg.server.port == 8000
