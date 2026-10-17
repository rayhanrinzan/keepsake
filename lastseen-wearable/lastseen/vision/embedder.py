"""Image embeddings. Adapted from the prototype's Embedder (OpenAI CLIP ViT-B/32)."""
from __future__ import annotations

from pathlib import Path
from typing import Protocol

import cv2
import numpy as np

from lastseen.types import Box
from lastseen.vision.geometry import clamp_box


class Embedder(Protocol):
    def embed(self, frame: np.ndarray, boxes: list[Box]) -> np.ndarray:
        """Return (N,512) L2-normalized float32 features, one per box."""

    def embed_text(self, texts: list[str]) -> np.ndarray:
        """Return (N,512) L2-normalized float32 text features."""


class ClipEmbedder:
    def __init__(self, device: str, models_dir: str | Path, crop_pad: float = 0.15):
        import clip  # lazy: heavy import
        import torch

        self._torch = torch
        self.device = device
        self.crop_pad = crop_pad
        self.model, self.preprocess = clip.load(
            "ViT-B/32", device=device, download_root=str(Path(models_dir) / "clip"))
        self.model.eval()

    def embed(self, frame, boxes):
        if not boxes:
            return np.zeros((0, 512), dtype=np.float32)
        from PIL import Image

        torch = self._torch
        h, w = frame.shape[:2]
        crops = []
        for x1, y1, x2, y2 in boxes:
            pad = int(self.crop_pad * max(x2 - x1, y2 - y1))
            x1, y1, x2, y2 = clamp_box([x1 - pad, y1 - pad, x2 + pad, y2 + pad], w, h)
            crop = cv2.cvtColor(frame[y1:y2, x1:x2], cv2.COLOR_BGR2RGB)
            crops.append(self.preprocess(Image.fromarray(crop)))
        with torch.no_grad():
            feats = self.model.encode_image(torch.stack(crops).to(self.device)).float()
            feats = feats / feats.norm(dim=-1, keepdim=True)
        return feats.cpu().numpy().astype(np.float32)

    def embed_text(self, texts):
        import clip

        torch = self._torch
        with torch.no_grad():
            tokens = clip.tokenize(list(texts)).to(self.device)
            feats = self.model.encode_text(tokens).float()
            feats = feats / feats.norm(dim=-1, keepdim=True)
        return feats.cpu().numpy().astype(np.float32)
