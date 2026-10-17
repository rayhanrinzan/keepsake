"""Open the webcam on the main thread once. On macOS this triggers the camera-permission
prompt for your terminal app (the server's background thread cannot show it).

    check_camera.py           list cameras macOS sees now
    check_camera.py 1         open camera 1
    check_camera.py iPhone    open the camera whose name contains "iPhone"
"""
import os
import sys

import cv2

from cameras import find_camera, list_cameras

arg = sys.argv[1] if len(sys.argv) > 1 else None
if arg is None:
    cams = list_cameras()
    for i, name in cams:
        print(f"{i}: {name}")
    if not cams:
        print("No cameras listed (an iPhone appears only while it's locked, still and near the Mac).")
    arg = os.getenv("CTRLF_CAMERA_NAME") or os.getenv("CTRLF_CAMERA_INDEX", "0")
if arg.isdigit():
    index = int(arg)
else:
    index = find_camera(arg)
    if index is None:
        print(f"No camera named \"{arg}\" right now.")
        sys.exit(1)
cap = cv2.VideoCapture(index)
ok, frame = cap.read() if cap.isOpened() else (False, None)
cap.release()
if ok:
    print(f"Camera {index} OK: {frame.shape[1]}x{frame.shape[0]}")
else:
    print(f"Camera {index} unavailable. Check it's connected, and that your terminal has camera access "
          "(System Settings > Privacy & Security > Camera).")
    sys.exit(1)
