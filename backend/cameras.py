"""Pick a camera by name ("iPhone") instead of by index.

OpenCV's macOS backend numbers cameras by sorting AVFoundation devices by uniqueID
(modules/videoio/src/cap_avfoundation_mac.mm). Continuity Camera only exists while the phone is
connected, so the same index can mean the iPhone on one run and the built-in camera on the next.
We build the same sorted list and look the name up each time the camera is opened.
"""
from __future__ import annotations

import logging

log = logging.getLogger("keepsake.cameras")


def list_cameras() -> list[tuple[int, str]]:
    """(OpenCV index, device name) for every camera macOS sees now. Empty if unavailable."""
    try:
        import AVFoundation as AV
    except ImportError:  # not macOS, or pyobjc-framework-AVFoundation not installed
        return []
    try:
        devices = list(AV.AVCaptureDevice.devicesWithMediaType_(AV.AVMediaTypeVideo))
        devices += list(AV.AVCaptureDevice.devicesWithMediaType_(AV.AVMediaTypeMuxed))
        devices.sort(key=lambda d: str(d.uniqueID()))  # same order OpenCV uses
        return [(i, str(d.localizedName())) for i, d in enumerate(devices)]
    except Exception:  # noqa: BLE001
        log.exception("couldn't list cameras")
        return []


def find_camera(name: str, cameras: list[tuple[int, str]] | None = None) -> int | None:
    """Index of the first camera whose name contains `name` (case-insensitive), or None."""
    cameras = list_cameras() if cameras is None else cameras
    want = name.strip().lower()
    for index, device in cameras:
        if want in device.lower():
            return index
    return None
