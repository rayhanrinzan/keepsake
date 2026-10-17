import numpy as np
import pytest

from lastseen.config import IdentityCfg
from lastseen.vision.geometry import iou
from lastseen.vision.identity import Gallery, Identity, template_candidates
from tests.fakes import FakeEmbedder

WHITE_BOX = (60, 40, 100, 70)
GRAY_BOX = (200, 120, 240, 150)


def make_frame():
    f = np.full((240, 320, 3), 100, np.uint8)
    f[40:70, 60:100] = 255
    f[120:150, 200:240] = 150
    return f


@pytest.fixture
def ident():
    return Identity(FakeEmbedder(), IdentityCfg())


@pytest.fixture
def gal_white(tmp_path):
    g = Gallery("case", tmp_path)
    g.pos = FakeEmbedder().embed(make_frame(), [WHITE_BOX])
    g.neg = FakeEmbedder().embed(make_frame(), [GRAY_BOX])
    return g


def test_accepts_own_item_rejects_lookalike(ident, gal_white):
    s = ident.score(make_frame(), gal_white, [WHITE_BOX, GRAY_BOX])
    assert ident.accepts(*s[0], False)
    assert not ident.accepts(*s[1], False)


def test_score_no_boxes(ident, gal_white):
    assert ident.score(make_frame(), gal_white, []) == []


def test_empty_neg_margin_equals_sim(ident, tmp_path):
    g = Gallery("case", tmp_path)
    g.pos = FakeEmbedder().embed(make_frame(), [WHITE_BOX])
    (sim, margin), = ident.score(make_frame(), g, [WHITE_BOX])
    assert margin == pytest.approx(sim)


def test_score_uses_one_embed_call(gal_white):
    emb = FakeEmbedder()
    Identity(emb, IdentityCfg()).score(make_frame(), gal_white, [WHITE_BOX, GRAY_BOX])
    assert emb.calls == 1


def test_template_finds_case():
    frame = np.full((240, 320, 3), 100, np.uint8)
    rng = np.random.default_rng(1)
    frame += rng.integers(0, 20, frame.shape, dtype=np.uint8)
    case = (120, 90, 180, 140)
    patch = rng.integers(0, 255, (50, 60), dtype=np.uint8)
    frame[90:140, 120:180] = patch[:, :, None]
    template = patch.copy()
    got = template_candidates(frame, template)
    assert iou(got[0], case) > 0.5


def test_template_skips_oversized():
    frame = np.zeros((12, 12, 3), np.uint8)
    assert template_candidates(frame, np.zeros((100, 100), np.uint8)) == []


def test_reacquire_stricter(ident):
    assert ident.accepts(0.82, 0.05, False)
    assert not ident.accepts(0.82, 0.03, True)  # margin below margin_reacquire
    assert not ident.accepts(0.74, 0.05, True)  # sim below thresh + bonus
    assert ident.accepts(0.76, 0.05, True)


def test_gallery_roundtrip(tmp_path):
    v = FakeEmbedder().embed(make_frame(), [WHITE_BOX, GRAY_BOX])
    g = Gallery("airpods", tmp_path)
    g.pos = v
    g.template = np.full((10, 12), 7, np.uint8)
    g.meta = {"display_name": "AirPods", "prompt": "airpods case", "origin": "enrolled",
              "created_ts": 1.0}
    g.save()
    g2 = Gallery.load("airpods", tmp_path)
    assert np.allclose(g2.pos, v)
    assert g2.neg.shape == (0, 512)
    assert g2.template.shape == (10, 12)
    assert g2.meta["origin"] == "enrolled"


def test_gallery_without_template(tmp_path):
    g = Gallery("x", tmp_path)
    g.pos = np.ones((1, 512), np.float32)
    g.save()
    assert not (tmp_path / "x" / "template.png").exists()
    assert Gallery.load("x", tmp_path).template is None


def test_gallery_cap_keeps_first(tmp_path):
    g = Gallery("x", tmp_path)
    rows = np.eye(512, dtype=np.float32)[:20]
    g.add_pos(rows[0])
    g.add_pos(rows[1:20])
    assert len(g.pos) == 12
    assert np.allclose(g.pos, rows[:12])


def test_empty_gallery_shapes(tmp_path):
    g = Gallery("x", tmp_path)
    assert g.pos.shape == (0, 512) and g.neg.shape == (0, 512)


def test_missing_gallery_is_none(tmp_path):
    assert Gallery.load("glasses", tmp_path) is None
    (tmp_path / "glasses").mkdir()
    assert Gallery.load("glasses", tmp_path) is None


def test_build_negatives_avoids_item_box():
    frame = make_frame()
    emb = FakeEmbedder()
    ident = Identity(emb, IdentityCfg())
    seen = []
    orig = emb.embed

    def spy(f, boxes):
        seen.extend(boxes)
        return orig(f, boxes)

    emb.embed = spy
    neg = ident.build_negatives(frame, WHITE_BOX, [GRAY_BOX, WHITE_BOX], n=12)
    assert neg.shape == (len(seen), 512) and len(seen) >= 12
    assert GRAY_BOX in seen  # look-alike kept
    assert all(iou(b, WHITE_BOX) < 0.1 for b in seen)
    # deterministic
    seen2 = []
    emb.embed = lambda f, b: (seen2.extend(b), orig(f, b))[1]
    ident.build_negatives(frame, WHITE_BOX, [GRAY_BOX, WHITE_BOX], n=12)
    assert seen == seen2


def test_module_level_accepts_matches_method():
    from lastseen.config import IdentityCfg
    from lastseen.vision.identity import accepts
    c = IdentityCfg()
    assert accepts(0.82, 0.05, False, c)
    assert not accepts(0.82, 0.03, True, c)
    assert not accepts(0.74, 0.05, True, c)
    assert accepts(0.76, 0.05, True, c)
    assert not accepts(0.69, 0.5, False, c)


def test_score_embeddings_matches_score(ident, gal_white):
    frame = make_frame()
    emb = FakeEmbedder().embed(frame, [WHITE_BOX, GRAY_BOX])
    assert ident.score_embeddings(emb, gal_white) == ident.score(frame, gal_white, [WHITE_BOX, GRAY_BOX])
    assert ident.score_embeddings(np.zeros((0, 512), np.float32), gal_white) == []


@pytest.mark.parametrize("bad", ["../x", "a/b", "", "..", "/abs"])
def test_gallery_rejects_escaping_ids(tmp_path, bad):
    with pytest.raises(ValueError):
        Gallery(bad, tmp_path)


def test_gallery_save_is_atomic(tmp_path, monkeypatch):
    import lastseen.vision.identity as ident

    g = Gallery("x", tmp_path)
    g.pos = np.ones((1, 512), np.float32)
    g.neg = np.ones((2, 512), np.float32)
    g.save()
    real_save, calls = np.save, []

    def flaky(f, arr, *a, **kw):
        calls.append(1)
        if len(calls) == 2:  # the neg.npy write fails half-way, after some bytes went out
            if hasattr(f, "write"):
                f.write(b"partial")
            else:
                open(f, "wb").write(b"partial")
            raise OSError("disk full")
        return real_save(f, arr, *a, **kw)

    monkeypatch.setattr(ident.np, "save", flaky)
    g.neg = np.zeros((5, 512), np.float32)
    with pytest.raises(OSError):
        g.save()
    monkeypatch.undo()
    assert sorted(p.name for p in (tmp_path / "x").iterdir()) == ["meta.json", "neg.npy", "pos.npy"]
    assert Gallery.load("x", tmp_path).neg.shape == (2, 512)  # previous content intact
