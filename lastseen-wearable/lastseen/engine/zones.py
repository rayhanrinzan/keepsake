"""Named polygon zones (normalized 0-1) that turn a box into words like "on the desk"."""
from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, get_args

import cv2
import numpy as np
from shapely.geometry import Point, Polygon

from lastseen.types import Box

log = logging.getLogger(__name__)

ZoneType = Literal["surface", "cover", "privacy"]
DEFAULT_COVER_PHRASE = "under the blanket on the {name}"
NEAR_FRAC = 0.15


@dataclass
class Zone:
    name: str
    type: ZoneType
    polygon: list[tuple[float, float]]
    cover_phrase: str | None = None

    def phrase(self) -> str:
        if self.type == "cover":
            return (self.cover_phrase or DEFAULT_COVER_PHRASE).format(name=self.name)
        return f"on the {self.name}"


def _anchor(box: Box) -> Point:
    x1, _, x2, y2 = box
    return Point((x1 + x2) / 2, y2)


def _parse_zone(z: dict) -> Zone:
    name, ztype = str(z["name"]), z["type"]
    if ztype not in get_args(ZoneType):
        raise ValueError(f"unknown zone type {ztype!r} for zone {name!r}")
    poly = [(float(pt[0]), float(pt[1])) for pt in z["polygon"]]
    if len(poly) < 3:
        raise ValueError(f"zone {name!r} has {len(poly)} points; needs at least 3")
    return Zone(name, ztype, poly, z.get("cover_phrase"))


class ZoneMap:
    def __init__(self, zones: list[Zone] | None = None):
        self.zones: list[Zone] = list(zones or [])

    @classmethod
    def load(cls, path) -> "ZoneMap":
        p = Path(path)
        if not p.exists():
            log.warning("zones file %s not found; running without zones", p)
            return cls([])
        try:
            data = json.loads(p.read_text())
            raw = data.get("zones", [])
            if not isinstance(raw, list):
                raise ValueError("'zones' is not a list")
        except Exception as e:  # a bad zones.json must never stop the app
            log.warning("zones file %s unreadable (%s); running without zones", p, e)
            return cls([])
        zones = []
        for i, z in enumerate(raw):
            try:
                zones.append(_parse_zone(z))
            except Exception as e:
                log.warning("skipping zone #%d in %s: %s", i, p, e)
        return cls(zones)

    def _poly(self, z: Zone, wh: tuple[int, int]) -> Polygon:
        w, h = wh
        return Polygon([(x * w, y * h) for x, y in z.polygon])

    def _visible(self):
        return [z for z in self.zones if z.type != "privacy"]

    def zone_at_point(self, pt: tuple[float, float], wh: tuple[int, int]) -> Zone | None:
        """First non-privacy zone (file order) containing the pixel point `pt`."""
        p = Point(pt)
        for z in self._visible():
            if self._poly(z, wh).intersects(p):
                return z
        return None

    def zone_at(self, box: Box, wh: tuple[int, int]) -> Zone | None:
        a = _anchor(box)
        return self.zone_at_point((a.x, a.y), wh)

    def nearest(self, box: Box, wh: tuple[int, int]) -> tuple[Zone | None, float]:
        pt = _anchor(box)
        best: Zone | None = None
        best_d = math.inf
        for z in self._visible():
            d = self._poly(z, wh).distance(pt)
            if d < best_d:
                best, best_d = z, d
        return best, best_d

    def describe(self, box: Box, wh: tuple[int, int]) -> str:
        z = self.zone_at(box, wh)
        if z is not None:
            return z.phrase()
        near, d = self.nearest(box, wh)
        if near is not None and d <= NEAR_FRAC * wh[0]:
            return f"on the floor near the {near.name}"
        return "in the room"

    def privacy_mask(self, wh: tuple[int, int]) -> np.ndarray | None:
        priv = [z for z in self.zones if z.type == "privacy"]
        if not priv:
            return None
        w, h = wh
        mask = np.zeros((h, w), np.uint8)
        for z in priv:
            pts = np.array([[x * w, y * h] for x, y in z.polygon], np.int32)
            cv2.fillPoly(mask, [pts], 255)
        return mask
