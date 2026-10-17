"""Wearable observation event contract (issue #4 / #5), shared with Photon and voice.

Stdlib only: consumers can import this file (or just read the JSON from GET /api/observations)
without pulling in OpenCV, Ultralytics or MediaPipe.

Every event is a flat JSON object:

    event_id     str   unique, stable ("obs-<32 hex>")
    event_type   str   one of EVENT_TYPES (below)
    object_id    str   e.g. "car_key_01" (catalog object_id)
    category     str   detector category, e.g. "car key"
    name         str   display name, e.g. "Keys"
    timestamp    str   ISO-8601 UTC of the frame the evidence ends on
    confidence   float 0..1, how sure we are of *this event type* (not just the detector score)
    bbox         [x0, y0, x1, y1] normalized box in that frame (only valid for that frame/view)
    snapshot_id  int | null   stored photo (GET /api/snapshots/{id}/image) once it has been written
    frame_id     int | null   worker frame counter (debugging)
    camera_mode  str   "wearable" or "fixed"
    view_id      str | null   camera view the bbox belongs to
    evidence     [str]        subset of EVIDENCE explaining why the event was emitted

What each type does and does NOT claim:

    object_observed       The item was seen steadily (several frames, camera fairly still).
                          Says nothing about whether it moved or who put it there.
    interaction_candidate A hand stayed on/next to the item. Proximity only; NOT a pickup.
    possible_pickup       After a hand interaction the item moved with the hand or left view with it
                          (camera steady). Probable, not certain.
    placement_confirmed   Only after a possible_pickup: the item reappeared, held still with no hand
                          on it and the camera steady. This is the "you put it down here" event.

Payload changes must be agreed with the Photon / voice owners; bump CONTRACT_VERSION when you do.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

CONTRACT_VERSION = 1

OBJECT_OBSERVED = "object_observed"
INTERACTION_CANDIDATE = "interaction_candidate"
POSSIBLE_PICKUP = "possible_pickup"
PLACEMENT_CONFIRMED = "placement_confirmed"
EVENT_TYPES = (OBJECT_OBSERVED, INTERACTION_CANDIDATE, POSSIBLE_PICKUP, PLACEMENT_CONFIRMED)

EVIDENCE = {
    "stable_object_detection": "detected in most of the recent frames at a consistent position",
    "camera_steady": "little background motion, so position changes are not camera panning",
    "hand_near_object": "a detected hand overlapped or touched the object's box for several frames",
    "object_moved_with_hand": "the object's box shifted together with an overlapping hand",
    "object_left_with_hand": "the object vanished while a hand was on it and stayed gone after the hand left",
    "prior_possible_pickup": "a possible_pickup for this object came first",
    "hand_released": "no hand on the object while it settled",
}

CAMERA_MODES = ("wearable", "fixed")
FIELDS = ("event_id", "event_type", "object_id", "category", "name", "timestamp", "confidence",
          "bbox", "snapshot_id", "frame_id", "camera_mode", "view_id", "evidence")


def new_event_id() -> str:
    return "obs-" + uuid.uuid4().hex


def make_event(event_type: str, *, object_id: str, category: str, name: str, timestamp: datetime,
               confidence: float, bbox, evidence: list[str], camera_mode: str = "wearable",
               view_id: str | None = None, frame_id: int | None = None,
               snapshot_id: int | None = None) -> dict:
    ts = timestamp if timestamp.tzinfo else timestamp.replace(tzinfo=timezone.utc)
    ev = {"event_id": new_event_id(), "event_type": event_type, "object_id": object_id,
          "category": category, "name": name,
          "timestamp": ts.astimezone(timezone.utc).isoformat(timespec="milliseconds"),
          "confidence": round(float(confidence), 3),
          "bbox": [round(float(v), 4) for v in bbox] if bbox else None,
          "snapshot_id": snapshot_id, "frame_id": frame_id, "camera_mode": camera_mode,
          "view_id": view_id, "evidence": list(evidence)}
    validate_event(ev)
    return ev


def validate_event(ev: dict) -> None:
    """Raise ValueError if `ev` breaks the contract (used by tests and before storing)."""
    missing = [f for f in FIELDS if f not in ev]
    if missing:
        raise ValueError(f"missing fields: {missing}")
    if ev["event_type"] not in EVENT_TYPES:
        raise ValueError(f"unknown event_type {ev['event_type']!r}")
    if ev["camera_mode"] not in CAMERA_MODES:
        raise ValueError(f"unknown camera_mode {ev['camera_mode']!r}")
    if not 0.0 <= ev["confidence"] <= 1.0:
        raise ValueError("confidence must be within 0..1")
    unknown = [e for e in ev["evidence"] if e not in EVIDENCE]
    if unknown or not ev["evidence"]:
        raise ValueError(f"evidence must be a non-empty subset of EVIDENCE, got {ev['evidence']}")
    if ev["event_type"] == PLACEMENT_CONFIRMED and "prior_possible_pickup" not in ev["evidence"]:
        raise ValueError("placement_confirmed requires prior_possible_pickup evidence")
    if ev["event_type"] == POSSIBLE_PICKUP and "hand_near_object" not in ev["evidence"]:
        raise ValueError("possible_pickup requires hand_near_object evidence")
    datetime.fromisoformat(ev["timestamp"])


def contract() -> dict:
    """Machine-readable description served at GET /api/observations/contract."""
    return {"version": CONTRACT_VERSION, "fields": list(FIELDS), "event_types": list(EVENT_TYPES),
            "evidence": EVIDENCE, "camera_modes": list(CAMERA_MODES)}
