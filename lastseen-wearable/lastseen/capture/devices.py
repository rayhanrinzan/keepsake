"""Find a camera's OpenCV index by name on macOS.

macOS lists video devices in an order that changes between runs, but OpenCV 5's AVFoundation
backend numbers them by `uniqueID` (checked live: the iPhone, uniqueID 266E..., was index 0 whether
macOS listed it first or second). So names sorted by uniqueID give the index for cv2.VideoCapture.
Indexes change as devices come and go (the iPhone only appears while Continuity Camera is
available), names don't.
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)


def camera_names() -> list[str]:
    """Video device names in OpenCV index order; [] when AVFoundation isn't available."""
    try:
        import AVFoundation as AV
    except Exception:
        return []
    try:
        return ordered_names(AV.AVCaptureDevice.devicesWithMediaType_(AV.AVMediaTypeVideo))
    except Exception:
        log.exception("listing cameras failed")
        return []


def ordered_names(devices) -> list[str]:
    """Device names in OpenCV's index order (by uniqueID)."""
    return [str(d.localizedName()) for d in sorted(devices, key=lambda d: str(d.uniqueID()))]


DESK_VIEW = "desk view"  # Continuity Camera's Desk View is a second, cropped device: never the room


def find_camera_index(name: str, names: list[str] | None = None) -> int | None:
    """Index of the camera named `name` (case-insensitive): an exact match first, else the first name
    containing it, skipping "Desk View" devices unless asked for. None when nothing matches."""
    names = camera_names() if names is None else names
    want = name.lower()
    low = [n.lower() for n in names]
    exact = next((i for i, n in enumerate(low) if n == want), None)
    if exact is not None:
        return exact
    return next((i for i, n in enumerate(low)
                 if want in n and (DESK_VIEW not in n or DESK_VIEW in want)), None)
