"""CLIP text classifier: which configured item is this crop (or none)?"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from lastseen.config import ItemCfg
from lastseen.types import Box

OTHER_PROMPTS = ["a hand", "a table", "a phone", "a cup", "a pen", "background"]


@dataclass
class Classification:
    item_id: str | None
    probs: dict[str, float]
    reason: str  # "ok" | "other" | "low" | "close"


def _unit(v: np.ndarray) -> np.ndarray:
    return v / max(float(np.linalg.norm(v)), 1e-12)


def _item_prompts(item: ItemCfg) -> list[str]:
    prompts = ([item.prompt] if item.prompt else []) + list(item.extra_prompts)
    return prompts or [item.display_name]


class ItemClassifier:
    def __init__(self, embedder, items: list[ItemCfg], min_prob: float = 0.45,
                 min_lead: float = 0.15, det_boost: float = 0.03, scale: float = 100.0):
        self.embedder = embedder
        self.min_prob = min_prob
        self.min_lead = min_lead
        self.det_boost = det_boost
        self.scale = scale
        self.text: dict[str, np.ndarray] = {}
        for item in items:
            embs = np.asarray(embedder.embed_text(_item_prompts(item)), dtype=np.float64)
            embs = embs / np.maximum(np.linalg.norm(embs, axis=1, keepdims=True), 1e-12)
            self.text[item.id] = _unit(embs.mean(axis=0))
        other = np.asarray(embedder.embed_text(OTHER_PROMPTS), dtype=np.float64)
        self.other = other / np.maximum(np.linalg.norm(other, axis=1, keepdims=True), 1e-12)

    def classify(self, frame, box: Box, det_item_ids: list[str],
                 candidates: list[str]) -> Classification:
        img = np.asarray(self.embedder.embed(frame, [box])[0], dtype=np.float64)
        logits = [self.scale * (float(img @ self.text[i])
                                + (self.det_boost if i in det_item_ids else 0.0))
                  for i in candidates]
        logits += [self.scale * float(img @ o) for o in self.other]
        z = np.asarray(logits)
        p = np.exp(z - z.max())
        p /= p.sum()
        n = len(candidates)
        probs = {i: float(p[k]) for k, i in enumerate(candidates)}
        probs["other"] = float(p[n:].sum())
        top = max(probs, key=probs.get)
        if top == "other":
            return Classification(None, probs, "other")
        if probs[top] < self.min_prob:
            return Classification(None, probs, "low")
        if probs[top] - max(v for k, v in probs.items() if k != top) < self.min_lead:
            return Classification(None, probs, "close")
        return Classification(top, probs, "ok")
