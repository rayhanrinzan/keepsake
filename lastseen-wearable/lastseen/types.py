"""Shared dataclasses passed between vision, engine and brain."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Box = tuple[int, int, int, int]


@dataclass
class Candidate:
    box: Box
    sim: float
    margin: float
    source: Literal["det", "tmpl", "change", "stored"]
    det_conf: float = 0.0


@dataclass
class Person:
    track_id: int
    box: Box
    feet: tuple[int, int]


@dataclass
class TickObs:
    ts: float
    frame_wh: tuple[int, int]
    hands: list[Box]
    candidates: list[Candidate]
    change_boxes: list[Box]
    persons: list[Person] = field(default_factory=list)
    left_view: list[int] = field(default_factory=list)


@dataclass
class TrackerEvent:
    kind: Literal["PICKED_UP", "PLACED", "SEEN", "HIDDEN", "CARRIED_OUT"]
    item_id: str
    ts: float
    from_zone: str | None
    to_zone: str | None
    bbox: Box | None
    confidence: float
