"""Identity check: is this candidate box *our* item? Gallery of positive/negative CLIP embeddings."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import cv2
import numpy as np

from lastseen.config import IdentityCfg
from lastseen.types import Box
from lastseen.vision.embedder import Embedder
from lastseen.vision.geometry import clamp_box, iou

_EMPTY = lambda: np.zeros((0, 512), dtype=np.float32)  # noqa: E731


def accepts(sim: float, margin: float, reacquire: bool, cfg: IdentityCfg) -> bool:
    """Is a scored candidate our item? Reacquiring (item lost) demands a higher sim and margin."""
    return (sim >= cfg.sim_thresh + (cfg.reacquire_bonus if reacquire else 0.0)
            and margin >= (cfg.margin_reacquire if reacquire else cfg.margin_follow))


def _atomic_write(path: Path, write) -> None:
    """write(f) into a temp file next to `path`, then os.replace it; no partial file is left."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            write(f)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class Gallery:
    def __init__(self, item_id: str, root: Path):
        self.item_id = item_id
        self.root = Path(root)
        if (self.root / item_id).resolve().parent != self.root.resolve():
            raise ValueError(f"gallery id {item_id!r} must name a directory directly under {self.root}")
        self.pos = _EMPTY()
        self.neg = _EMPTY()
        self.template: np.ndarray | None = None
        self.meta: dict = {}

    @property
    def dir(self) -> Path:
        return self.root / self.item_id

    def add_pos(self, emb: np.ndarray, cap: int = 12) -> None:
        emb = np.asarray(emb, dtype=np.float32).reshape(-1, 512)
        # Keeps the first-enrolled rows; the newest rows beyond the cap are dropped.
        self.pos = np.concatenate([self.pos, emb])[:cap]

    def save(self) -> None:
        """Each file is written to a temp file in the same dir, then renamed over the old one."""
        d = self.dir
        d.mkdir(parents=True, exist_ok=True)
        for name, arr in (("pos.npy", self.pos), ("neg.npy", self.neg)):
            _atomic_write(d / name, lambda f, arr=arr: np.save(f, arr))
        if self.template is not None:
            ok, buf = cv2.imencode(".png", self.template)
            if not ok:
                raise ValueError(f"could not encode template for {self.item_id}")
            _atomic_write(d / "template.png", lambda f: f.write(buf.tobytes()))
        _atomic_write(d / "meta.json", lambda f: f.write(json.dumps(self.meta).encode()))

    @classmethod
    def load(cls, item_id: str, root: Path) -> "Gallery | None":
        g = cls(item_id, root)
        if not (g.dir / "pos.npy").is_file():
            return None
        g.pos = np.load(g.dir / "pos.npy").astype(np.float32).reshape(-1, 512)
        if (g.dir / "neg.npy").is_file():
            g.neg = np.load(g.dir / "neg.npy").astype(np.float32).reshape(-1, 512)
        t = g.dir / "template.png"
        if t.is_file():
            g.template = cv2.imread(str(t), cv2.IMREAD_GRAYSCALE)
        if (g.dir / "meta.json").is_file():
            g.meta = json.loads((g.dir / "meta.json").read_text())
        return g


class Identity:
    def __init__(self, embedder: Embedder, cfg: IdentityCfg):
        self.embedder = embedder
        self.cfg = cfg

    def score(self, frame, gallery: Gallery, boxes: list[Box]) -> list[tuple[float, float]]:
        """(sim, margin) per box: sim = max cosine to pos, margin = sim - max cosine to neg."""
        if not boxes:
            return []
        return self.score_embeddings(self.embedder.embed(frame, boxes), gallery)

    @staticmethod
    def score_embeddings(emb: np.ndarray, gallery: Gallery) -> list[tuple[float, float]]:
        """(sim, margin) per precomputed embedding row (lets one embed call serve many galleries)."""
        if len(emb) == 0:
            return []
        sim = (emb @ gallery.pos.T).max(axis=1)
        neg = (emb @ gallery.neg.T).max(axis=1) if len(gallery.neg) else np.zeros(len(emb))
        return [(float(s), float(s - n)) for s, n in zip(sim, neg)]

    def accepts(self, sim: float, margin: float, reacquire: bool) -> bool:
        return accepts(sim, margin, reacquire, self.cfg)

    def build_negatives(self, frame, item_box: Box, extra_boxes: list[Box], n: int = 12) -> np.ndarray:
        """Embed look-alike boxes plus random background patches away from the item."""
        h, w = frame.shape[:2]
        bw, bh = item_box[2] - item_box[0], item_box[3] - item_box[1]
        rng = np.random.default_rng(0)
        boxes = [b for b in extra_boxes if iou(b, item_box) < 0.1]
        tries = 0
        while len(boxes) < n and tries < 1000:
            tries += 1
            s = rng.uniform(0.6, 1.6)
            x = rng.uniform(0, max(1, w - bw * s))
            y = rng.uniform(0, max(1, h - bh * s))
            b = clamp_box([x, y, x + bw * s, y + bh * s], w, h)
            if iou(b, item_box) < 0.05:
                boxes.append(b)
        return self.embedder.embed(frame, boxes[: n + 6])


def template_candidates(frame, template: np.ndarray, k: int = 3) -> list[Box]:
    """Multi-scale template match against the enrolled crop, for when the detector misses."""
    if template is None:
        return []
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
    th, tw = template.shape[:2]
    h, w = gray.shape
    cands = []
    for s in (0.15, 0.25, 0.35, 0.5, 0.7, 1.0, 1.3):
        nh, nw = int(th * s), int(tw * s)
        if nh < 8 or nw < 8:
            continue
        t = cv2.resize(template, (nw, nh))
        if nh >= h or nw >= w:
            continue
        res = cv2.matchTemplate(gray, t, cv2.TM_CCOEFF_NORMED)
        for _ in range(k):
            _, mv, _, ml = cv2.minMaxLoc(res)
            cands.append(((ml[0], ml[1], ml[0] + nw, ml[1] + nh), mv))
            cv2.rectangle(res, (ml[0] - nw // 2, ml[1] - nh // 2),
                          (ml[0] + nw // 2, ml[1] + nh // 2), -1, -1)
    cands.sort(key=lambda c: -c[1])
    return [c[0] for c in cands[:k]]
