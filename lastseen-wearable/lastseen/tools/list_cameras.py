"""List cameras: python -m lastseen.tools.list_cameras

Continuity Camera's index changes between runs; run this before every demo.
"""
from __future__ import annotations

import time
from pathlib import Path

import cv2


def main() -> None:
    from lastseen.capture.devices import camera_names
    for i, n in enumerate(camera_names()):
        print(f"camera {i} name: {n}")
    out = Path("data")
    out.mkdir(exist_ok=True)
    for i in range(6):
        cap = cv2.VideoCapture(i)
        frame = None
        deadline = time.monotonic() + 3.0
        while cap.isOpened() and time.monotonic() < deadline:
            ok, frame = cap.read()
            if ok and frame is not None:
                break
            frame = None
            time.sleep(0.1)
        cap.release()
        if frame is None:
            print(f"camera {i}: none")
        else:
            h, w = frame.shape[:2]
            cv2.imwrite(str(out / f"cam_{i}.jpg"), frame)
            print(f"camera {i}: {w}x{h}")


if __name__ == "__main__":
    main()
