"""Surroundings sentence from the last photo (Grok vision), with a stand-in for the API."""
import cv2
import numpy as np

from describe import SceneDescriber, clean
from memory import answer_query


def photo(tmp_path):
    p = tmp_path / "keys.jpg"
    cv2.imwrite(str(p), np.full((90, 160, 3), 120, np.uint8))
    return p


def describer(monkeypatch, reply):
    monkeypatch.setenv("CTRLF_DESCRIBE", "1")
    monkeypatch.setenv("XAI_API_KEY", "test-key")
    sent = []

    def post(body):
        sent.append(body)
        if isinstance(reply, Exception):
            raise reply
        return reply
    return SceneDescriber(post=post), sent


def test_clean_keeps_one_plain_sentence():
    assert clean("It was on a green round seat next to a gold bottle. Also a chair.") == \
        "It was on a green round seat next to a gold bottle."
    assert clean('"It was on the brown table"') == "It was on the brown table."
    assert clean("UNSURE") is None
    assert clean("I think there is a chair") is None  # not an answer in the expected form
    assert clean("It was " + "very " * 40 + "far.") is None
    assert clean(None) is None


def test_describes_once_per_photo_with_the_item_named(monkeypatch, tmp_path):
    d, sent = describer(monkeypatch, "It was on a green seat next to a water bottle.")
    p = photo(tmp_path)
    assert d.describe(7, p, "keys", (0.1, 0.1, 0.4, 0.5)) == "It was on a green seat next to a water bottle."
    assert d.describe(7, p, "keys", (0.1, 0.1, 0.4, 0.5)) == "It was on a green seat next to a water bottle."
    assert len(sent) == 1  # cached for the same photo
    content = sent[0]["messages"][0]["content"]
    assert content[0]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert "keys" in content[1]["text"]


def test_failures_and_switches_give_no_sentence(monkeypatch, tmp_path):
    p = photo(tmp_path)
    d, sent = describer(monkeypatch, RuntimeError("offline"))
    assert d.describe(1, p, "keys") is None
    monkeypatch.setenv("CTRLF_DESCRIBE", "0")
    d, sent = describer(monkeypatch, "It was on a desk.")
    monkeypatch.setenv("CTRLF_DESCRIBE", "0")
    assert d.describe(2, p, "keys") is None and sent == []
    monkeypatch.setenv("CTRLF_DESCRIBE", "1")
    monkeypatch.delenv("XAI_API_KEY")
    assert d.describe(3, p, "keys") is None and sent == []
    assert d.describe(4, None, "keys") is None


def test_answer_includes_the_sentence_when_there_is_a_photo():
    obj = {"seen": True, "last_seen": "2026-10-18T02:25:00+00:00", "visible": False, "snapshot": {"id": 3, "bbox": [0, 0, 1, 1]}}
    r = answer_query("where are my keys", lambda cat: obj, lambda o, noun: "It was on a green seat.")
    assert "It was on a green seat." in r["answer"] and r["surroundings"] == "It was on a green seat."
    r = answer_query("where are my keys", lambda cat: obj, lambda o, noun: None)
    assert "It was" not in r["answer"] and r["surroundings"] is None
    no_photo = {**obj, "snapshot": None}
    r = answer_query("where are my keys", lambda cat: no_photo, lambda o, noun: 1 / 0)  # never called
    assert r["found"] and r["surroundings"] is None
