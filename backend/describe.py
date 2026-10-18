"""Describe where an item was in its last photo, using nearby big things as reference points.

"I last saw your keys 4 minutes ago" becomes "... It was on a green round seat next to a gold water
bottle." The item's newest photo (with its box drawn on) goes to a Grok vision model, which answers in
one short sentence about what it can see around the item. Nothing here guesses a room position: it only
describes the photo, and the photo stays on screen as proof.

Only the one photo being asked about is sent to xAI (needs XAI_API_KEY). Answers are cached per photo.
Any failure (no key, offline, slow, odd reply) returns None and the answer is given without it.
Env: CTRLF_DESCRIBE=0 turns it off; CTRLF_VISION_MODEL picks the model; CTRLF_DESCRIBE_TIMEOUT (s).
"""
from __future__ import annotations

import base64
import logging
import os
import re
import threading
from pathlib import Path

log = logging.getLogger("keepsake.describe")

API = "https://api.x.ai/v1/chat/completions"
PROMPT = (
    "This photo is from a camera worn on someone's chest. The green box marks their {item}. "
    "In ONE short sentence of at most 20 words, say where the {item} is, using big, easy-to-spot things "
    "around it as reference points (furniture, surfaces, their colors, other objects next to it), "
    "e.g. 'It was on a green round seat next to a gold water bottle.' Only mention things you can clearly "
    "see. Do not mention the box, the photo or the camera. Start with 'It was'. If you can't tell, reply "
    "only with: UNSURE"
)


def enabled() -> bool:
    return os.getenv("CTRLF_DESCRIBE", "1") != "0" and bool(os.getenv("XAI_API_KEY"))


def clean(text: str | None) -> str | None:
    """Keep one plain sentence that starts like an answer; drop anything unusable."""
    if not text:
        return None
    t = " ".join(text.strip().strip('"').split())
    if not t or "UNSURE" in t.upper() or not t.lower().startswith("it was"):
        return None
    t = re.split(r"(?<=[.!?])\s", t, maxsplit=1)[0]  # first sentence only
    if len(t.split()) > 30:
        return None
    return t if t[-1] in ".!?" else t + "."


def _boxed_jpeg(path: Path, bbox) -> bytes:
    """The photo with the item's box drawn on it, so the model knows which thing we mean."""
    data = path.read_bytes()
    if not bbox:
        return data
    try:
        import cv2
        import numpy as np
        img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        h, w = img.shape[:2]
        x0, y0, x1, y1 = bbox
        cv2.rectangle(img, (int(x0 * w), int(y0 * h)), (int(x1 * w), int(y1 * h)), (0, 220, 0), max(2, w // 200))
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])
        return buf.tobytes() if ok else data
    except Exception:  # noqa: BLE001
        return data


class SceneDescriber:
    def __init__(self, post=None):
        self._cache: dict[int, str | None] = {}  # snapshot id -> sentence (None: tried, no answer)
        self._lock = threading.Lock()
        self._post = post  # injectable for tests: (json_body) -> reply text

    def describe(self, snapshot_id: int, path: Path | None, item: str, bbox=None) -> str | None:
        if not enabled() or path is None:
            return None
        with self._lock:
            if snapshot_id in self._cache:
                return self._cache[snapshot_id]
        try:
            image = base64.b64encode(_boxed_jpeg(path, bbox)).decode()
            body = {
                "model": os.getenv("CTRLF_VISION_MODEL", "grok-4.7"),
                "temperature": 0.1,
                "messages": [{"role": "user", "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image}", "detail": "high"}},
                    {"type": "text", "text": PROMPT.format(item=item)},
                ]}],
            }
            text = clean((self._post or self._xai)(body))
        except Exception as e:  # noqa: BLE001
            log.warning("describe failed: %s", e)
            return None  # not cached: a network blip shouldn't stick
        with self._lock:
            self._cache[snapshot_id] = text
        return text

    @staticmethod
    def _xai(body: dict) -> str | None:
        import httpx
        r = httpx.post(API, json=body, timeout=float(os.getenv("CTRLF_DESCRIBE_TIMEOUT", "8")),
                       headers={"Authorization": f"Bearer {os.environ['XAI_API_KEY']}"})
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
