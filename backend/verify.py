"""Second-opinion check for detections: CLIP compares each box against the item and its look-alikes.

The trained detector (items.pt) and YOLO-World both fire confidently on things that resemble an item
(seen on real chest-camera frames: shoes and carpet as "wallet", a notebook and a chair as "keys",
laptop keyboards and people's faces as "glasses"). A detection survives only if CLIP rates the crop as
the item more than as any of that item's look-alikes. On 33 hand-checked real crops this kept all 3
real items and dropped all 30 false hits; the look-alike lists below came from that footage.

Optional: if CLIP can't load, every detection passes through unchanged.
"""
from __future__ import annotations

import logging
import time

import cv2
import numpy as np

log = logging.getLogger("keepsake.verify")

_COMMON = ["a laptop keyboard", "a carpet floor", "a person's face", "a person", "a hand", "a couch",
           "a table"]
# category -> (what the item looks like, what the detector mistakes for it)
PROMPTS: dict[str, tuple[list[str], list[str]]] = {
    "glasses": (["a pair of eyeglasses lying on a surface", "folded glasses on a table"],
                _COMMON + ["a person wearing glasses", "a smartphone", "a bag"]),
    "car key": (["a set of keys on a keyring", "car keys", "keys with a keychain tag", "a keychain"],
                _COMMON + ["a notebook", "a sheet of paper", "a chair", "a pen"]),
    "wallet": (["a wallet", "a leather wallet"],
               _COMMON + ["a shoe", "sneakers", "a smartphone", "a water bottle", "a book"]),
    "airpods case": (["an AirPods case", "a small white earbuds case"],
                     _COMMON + ["a white mug", "a phone charger", "a shoe"]),
}
MIN_SCORE = 0.25  # the item's share of CLIP's probability must also reach this
CACHE_SECONDS = 1.0  # a box near the last checked one reuses its verdict this long (CLIP ~55 ms/box)
CACHE_DISTANCE = 0.12  # "near": box centers within this fraction of the frame


class ClipVerifier:
    def __init__(self, device: str = "cpu", model_name: str = "ViT-B/32"):
        self._cache: dict[str, tuple[float, tuple[float, float], bool]] = {}  # category -> (t, center, keep)
        self.available = False
        self.reason = ""
        self.device = device
        try:
            import clip
            import torch
            self._torch = torch
            self._model, self._pre = clip.load(model_name, device=device)
            self._text: dict[str, tuple[int, object]] = {}
            with torch.no_grad():
                for cat, (pos, neg) in PROMPTS.items():
                    t = self._model.encode_text(clip.tokenize(pos + neg).to(device))
                    self._text[cat] = (len(pos), t / t.norm(dim=-1, keepdim=True))
            self.available = True
            log.info("CLIP verification on (%s)", ", ".join(PROMPTS))
        except Exception as e:  # noqa: BLE001
            self.reason = f"CLIP verification off: {e}"
            log.warning(self.reason)

    @staticmethod
    def _crop(frame: np.ndarray, bbox) -> np.ndarray | None:
        h, w = frame.shape[:2]
        x0, y0, x1, y1 = bbox[0] * w, bbox[1] * h, bbox[2] * w, bbox[3] * h
        pad = 0.15 * max(x1 - x0, y1 - y0)
        crop = frame[int(max(0, y0 - pad)):int(min(h, y1 + pad)), int(max(0, x0 - pad)):int(min(w, x1 + pad))]
        return crop if crop.size else None

    def score(self, frame: np.ndarray, category: str, bbox) -> tuple[float, float]:
        """(item probability, best look-alike probability) for one box."""
        return self.scores(frame, [(category, bbox)])[0]

    def scores(self, frame: np.ndarray, boxes: list[tuple[str, tuple]]) -> list[tuple[float, float]]:
        from PIL import Image
        torch = self._torch
        crops = [self._crop(frame, b) for _, b in boxes]
        idx = [i for i, c in enumerate(crops) if c is not None]
        out = [(0.0, 1.0)] * len(boxes)
        if not idx:
            return out
        batch = torch.stack([self._pre(Image.fromarray(cv2.cvtColor(crops[i], cv2.COLOR_BGR2RGB)))
                             for i in idx]).to(self.device)
        with torch.no_grad():
            img = self._model.encode_image(batch)
            img = img / img.norm(dim=-1, keepdim=True)
            for row, i in enumerate(idx):
                n_pos, text = self._text[boxes[i][0]]
                p = (100 * img[row:row + 1] @ text.T).softmax(-1)[0].tolist()
                out[i] = (sum(p[:n_pos]), max(p[n_pos:]))
        return out

    def _cached(self, o, now: float) -> bool | None:
        hit = getattr(self, "_cache", {}).get(o.category)
        if hit is None or now - hit[0] > CACHE_SECONDS:
            return None
        cx, cy = (o.bbox[0] + o.bbox[2]) / 2, (o.bbox[1] + o.bbox[3]) / 2
        if abs(cx - hit[1][0]) > CACHE_DISTANCE or abs(cy - hit[1][1]) > CACHE_DISTANCE:
            return None
        return hit[2]

    def keep(self, frame: np.ndarray, observations: list, now: float | None = None) -> list:
        """Drop detections of checked items that CLIP rates as a look-alike. Others pass through."""
        if not self.available:
            return observations
        now = time.monotonic() if now is None else now
        verdict, fresh = {}, []
        for o in observations:
            if o.category in PROMPTS and o.bbox:
                cached = self._cached(o, now)
                if cached is None:
                    fresh.append(o)
                else:
                    verdict[id(o)] = cached
        if fresh:
            cache = getattr(self, "_cache", None)
            for o, (item, other) in zip(fresh, self.scores(frame, [(o.category, o.bbox) for o in fresh])):
                verdict[id(o)] = ok = item > other and item >= MIN_SCORE
                if cache is not None:
                    cache[o.category] = (now, ((o.bbox[0] + o.bbox[2]) / 2, (o.bbox[1] + o.bbox[3]) / 2), ok)
        return [o for o in observations if verdict.get(id(o), True)]
