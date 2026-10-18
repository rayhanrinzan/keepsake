import numpy as np

from lastseen.config import ItemCfg
from lastseen.vision.classify import OTHER_PROMPTS, ItemClassifier

ITEMS = [
    ItemCfg(id="airpods", display_name="AirPods", prompt="airpods case"),
    ItemCfg(id="glasses", display_name="glasses", prompt="glasses"),
    ItemCfg(id="playing_cards", display_name="playing cards", prompt="playing cards"),
    ItemCfg(id="water_bottle", display_name="water bottle", prompt="water bottle"),
]
ALL = [i.id for i in ITEMS]
TEXT_AXIS = {"airpods case": 0, "glasses": 1, "playing cards": 2, "water bottle": 3,
             **{p: 10 + k for k, p in enumerate(OTHER_PROMPTS)}}


def axis(i):
    v = np.zeros(512, np.float32)
    v[i] = 1.0
    return v


def unit(v):
    v = np.asarray(v, np.float32)
    return v / np.linalg.norm(v)


class ScriptedEmbedder:
    """embed returns the chosen image vector; embed_text maps each text to a basis vector."""

    def __init__(self, img):
        self.img = unit(img)

    def embed(self, frame, boxes):
        return np.stack([self.img for _ in boxes])

    def embed_text(self, texts):
        return np.stack([axis(TEXT_AXIS.get(t, 100)) for t in texts])


def classify(img, candidates=ALL, det=(), **kw):
    clf = ItemClassifier(ScriptedEmbedder(img), ITEMS, **kw)
    return clf.classify(np.zeros((50, 50, 3), np.uint8), (0, 0, 10, 10), list(det), candidates)


def test_clear_match_locks():
    c = classify(axis(0))
    assert c.item_id == "airpods" and c.reason == "ok"


def test_other_wins():
    c = classify(axis(TEXT_AXIS["a cup"]))
    assert c.item_id is None and c.reason == "other"


def test_close_call_rejected():
    c = classify(axis(1) + axis(2))
    assert c.item_id is None and c.reason == "close"


def test_low_confidence_rejected():
    c = classify(axis(300))  # orthogonal to every text
    assert c.item_id is None and c.reason in ("low", "other")


def test_only_candidates_considered():
    c = classify(axis(0), candidates=["glasses", "playing_cards"])
    assert c.item_id != "airpods" and "airpods" not in c.probs


def test_det_label_boost_breaks_tie():
    img = axis(1) + axis(2)
    assert classify(img).reason == "close"
    # det_boost 0.05 -> a 5-logit edge (~150x), large enough to flip the exact tie
    c = classify(img, det=["glasses"], det_boost=0.05)
    assert c.item_id == "glasses" and c.reason == "ok"


def test_probs_keys():
    cands = ["airpods", "glasses"]
    c = classify(axis(0), candidates=cands)
    assert set(c.probs) == set(cands) | {"other"}
    assert abs(sum(c.probs.values()) - 1) < 1e-6
