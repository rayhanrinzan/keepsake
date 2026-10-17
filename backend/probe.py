"""Find which words YOLO-World recognises your items by.

Run (with the backend stopped):  ../.venv/bin/python probe.py
Hold each item in view. Every second it prints the best score for each prompt.
Pick the prompt with the highest score per item and put it as "category" in catalog.py.
"""
import os
import time

import cv2
from ultralytics import YOLO

PROMPTS = [
    "water bottle",
    "keys", "key", "keychain", "car key",
    "earbuds", "airpods", "airpods case", "white earbuds case", "earphones",
    "wallet", "leather wallet", "card holder", "black wallet", "brown wallet", "billfold", "purse", "phone case",
    "glasses", "eyeglasses", "glasses case", "sunglasses",
]
model = YOLO(os.path.join(os.path.dirname(__file__), "models", "yolov8s-worldv2.pt"))
model.set_classes(PROMPTS)
cap = cv2.VideoCapture(int(os.getenv("CTRLF_CAMERA_INDEX", "0")))
print("Press Ctrl+C to stop.")
while True:
    ok, frame = cap.read()
    if not ok:
        continue
    res = model.predict(frame, conf=0.02, imgsz=1280, verbose=False)[0]
    best = {}
    for c, cf in zip(res.boxes.cls.int().tolist(), res.boxes.conf.tolist()):
        best[PROMPTS[c]] = max(best.get(PROMPTS[c], 0), cf)
    line = "  ".join(f"{k} {v:.2f}" for k, v in sorted(best.items(), key=lambda x: -x[1])[:8])
    print(line or "(nothing)")
    time.sleep(1)
