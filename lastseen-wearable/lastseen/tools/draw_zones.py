"""One-off zone editor: python -m lastseen.tools.draw_zones [--camera N] [--out zones.json]

Left-click adds points, Enter closes the polygon (then name/type are asked in the
terminal), 'u' undoes a point, 's' saves, 'q' quits (saving unsaved zones).
"""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

import cv2
import numpy as np

from lastseen.capture.camera import LatestFrameCamera
from lastseen.config import load_config

TYPES = ("surface", "cover", "privacy")
COLORS = {"surface": (0, 200, 0), "cover": (0, 160, 255), "privacy": (0, 0, 255)}


def grab_frame(source, width) -> np.ndarray:
    cam = LatestFrameCamera(source, width)
    cam.start()
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            frame, _, _ = cam.get_latest()
            if frame is not None:
                return frame.copy()
            time.sleep(0.1)
    finally:
        cam.stop()
    raise SystemExit("no frame from camera")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--camera", default=None)
    ap.add_argument("--out", default="zones.json")
    args = ap.parse_args()
    cfg = load_config(os.environ.get("LASTSEEN_CONFIG", "config.yaml"))
    source = cfg.camera.source
    if args.camera is not None:
        source = int(args.camera) if args.camera.isdigit() else args.camera
    frame = grab_frame(source, cfg.camera.width)
    h, w = frame.shape[:2]

    out = Path(args.out)
    zones: list[dict] = json.loads(out.read_text()).get("zones", []) if out.exists() else []
    points: list[tuple[int, int]] = []
    dirty = False

    def on_mouse(event, x, y, *_):
        if event == cv2.EVENT_LBUTTONDOWN:
            points.append((x, y))

    def save():
        nonlocal dirty
        out.write_text(json.dumps({"zones": zones}, indent=2))
        dirty = False
        print(f"saved {len(zones)} zones to {out}")

    win = "draw zones"
    cv2.namedWindow(win)
    cv2.setMouseCallback(win, on_mouse)
    while True:
        img = frame.copy()
        for z in zones:
            pts = np.array([[x * w, y * h] for x, y in z["polygon"]], np.int32)
            col = COLORS[z["type"]]
            cv2.polylines(img, [pts], True, col, 2)
            cv2.putText(img, z["name"], tuple(pts[0]), cv2.FONT_HERSHEY_SIMPLEX, 0.7, col, 2)
        if points:
            cv2.polylines(img, [np.array(points, np.int32)], False, (255, 255, 0), 2)
            for p in points:
                cv2.circle(img, p, 4, (255, 255, 0), -1)
        cv2.imshow(win, img)
        k = cv2.waitKey(30) & 0xFF
        if k == ord("u") and points:
            points.pop()
        elif k in (13, 10) and len(points) >= 3:
            name = input("zone name: ").strip()
            ztype = input(f"type {TYPES}: ").strip()
            if name and ztype in TYPES:
                zones.append({"name": name, "type": ztype,
                              "polygon": [[round(x / w, 4), round(y / h, 4)] for x, y in points]})
                dirty = True
                points.clear()
            else:
                print("need a name and a valid type; polygon kept, press Enter to retry")
        elif k == ord("s"):
            save()
        elif k == ord("q"):
            if dirty:
                save()
            break
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
