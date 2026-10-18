"""
Task 0 corner check (throwaway, pre-event). Measures whether the corner camera can see what the real build needs.

  1. Press R and draw a tight box around the AirPods case where it lies (desk, tray, bed...). Leave it still.
  2. Press M: 10 s measurement of the case at that spot (detector hit rate, CLIP gap, size on screen).
     Move the case to another spot and repeat R + M.
  3. Press P, then walk around and to the taped door: 10 s of person / ankle / wrist detection.
  4. Press Q: prints a summary and appends it to NOTES.md.

  --list  prints which camera indexes work (Continuity Camera's index changes between runs).
"""

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "legacy"))
import lastseen_demo as d  # noqa: E402  (reuses the measured detector + CLIP settings)

from ultralytics import YOLO  # noqa: E402

WIN = "Corner check"
KPT_CONF = 0.3


def list_cameras():
    for i in range(6):
        cap = cv2.VideoCapture(i)
        ok, f = False, None
        for _ in range(30):  # Continuity Camera can take a second or two to deliver its first frame
            if not cap.isOpened():
                break
            ok, f = cap.read()
            if ok:
                break
            time.sleep(0.1)
        print(f"camera {i}: {'%dx%d' % (f.shape[1], f.shape[0]) if ok else 'none'}")
        cap.release()


def grab(cap, width=1280):
    ok, f = cap.read()
    if not ok:
        return None
    return cv2.resize(f, (width, int(f.shape[0] * width / f.shape[1])))


def measure_case(cap, tracker, spot, label, seconds=10):
    hits, sims, gaps, off_gaps, n, t_det = 0, [], [], [], 0, []
    t0 = time.time()
    while time.time() - t0 < seconds:
        f = grab(cap)
        if f is None:
            continue
        n += 1
        t = time.time()
        dets = [b for b, _ in tracker.detect(f, d.DET_CONF)]
        t_det.append(time.time() - t)
        on = [b for b in dets if d.iou(b, spot) > 0.3]
        hits += bool(on)
        cands = (on[:1] or [spot]) + [b for b in dets if d.iou(b, spot) < 0.1][: d.MAX_DETS]
        s, m = tracker.similarity(f, cands)
        sims.append(s[0])
        gaps.append(m[0])
        if len(m) > 1:
            off_gaps.append(m[1:].max())
        view = f.copy()
        cv2.rectangle(view, spot[:2], spot[2:], (0, 255, 120) if on else (0, 0, 255), 2)
        cv2.putText(view, f"measuring {label}: {time.time() - t0:.0f}/{seconds}s  hit {hits}/{n}", (12, 30), 0, 0.8, (255, 255, 255), 2)
        cv2.imshow(WIN, view)
        cv2.waitKey(1)
    w, h = spot[2] - spot[0], spot[3] - spot[1]
    return (f"case @ {label}: {w}x{h}px  detector hit {100 * hits / max(n, 1):.0f}%  "
            f"CLIP sim {np.mean(sims):.2f}  gap {np.mean(gaps):+.2f} (best elsewhere {max(off_gaps, default=float('nan')):+.2f})  "
            f"detector {1000 * np.mean(t_det):.0f} ms/frame")


def measure_people(cap, pose, seconds=10):
    n, person, ankles, wrists, ids, t_pose = 0, 0, 0, 0, set(), []
    t0 = time.time()
    while time.time() - t0 < seconds:
        f = grab(cap)
        if f is None:
            continue
        n += 1
        t = time.time()
        r = pose.track(f, persist=True, tracker="bytetrack.yaml", classes=[0], verbose=False, device=d.DEVICE)[0]
        t_pose.append(time.time() - t)
        view = r.plot()
        if r.boxes is not None and len(r.boxes):
            person += 1
            if r.boxes.is_track:
                ids.update(r.boxes.id.int().cpu().tolist())
            kc = r.keypoints.conf
            if kc is not None:
                kc = kc.cpu().numpy()
                ankles += bool(((kc[:, 15] > KPT_CONF) & (kc[:, 16] > KPT_CONF)).any())
                wrists += bool(((kc[:, 9] > KPT_CONF) | (kc[:, 10] > KPT_CONF)).any())
        cv2.putText(view, f"walk to the door: {time.time() - t0:.0f}/{seconds}s", (12, 30), 0, 0.8, (255, 255, 255), 2)
        cv2.imshow(WIN, view)
        cv2.waitKey(1)
    pct = lambda k: f"{100 * k / max(n, 1):.0f}%"  # noqa: E731
    return (f"people: person found {pct(person)}  both ankles {pct(ankles)}  a wrist {pct(wrists)}  "
            f"track ids seen {sorted(ids)}  pose {1000 * np.mean(t_pose or [0]):.0f} ms/frame")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--camera", type=int, default=0)
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()
    if args.list:
        return list_cameras()

    print(f"Loading models on {d.DEVICE}...")
    det = d.YOLOWorld(str(d.MODELS / "yolov8s-worldv2.pt"))
    det.set_classes(d.PROMPTS)
    tracker = d.Tracker(det, d.Embedder(), 0.70)
    pose = YOLO(str(d.MODELS / "yolo26n-pose.pt"))  # downloads ~7 MB on first run

    cap = cv2.VideoCapture(args.camera)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
    if not cap.isOpened():
        raise SystemExit("Couldn't open the camera. Try --list, and allow camera access for your terminal.")
    cv2.namedWindow(WIN, cv2.WINDOW_NORMAL)
    results, spot, spots = [], None, 0

    while True:
        f = grab(cap)
        if f is None:
            cv2.waitKey(1)
            continue
        view = f.copy()
        if spot:
            cv2.rectangle(view, spot[:2], spot[2:], (0, 255, 120), 2)
        cv2.putText(view, "R draw box on case   M measure case   P measure people   Q quit", (12, 30), 0, 0.7, (255, 255, 255), 2)
        for i, line in enumerate(results[-4:]):
            cv2.putText(view, line[:110], (12, view.shape[0] - 20 - 24 * i), 0, 0.5, (0, 255, 255), 1)
        cv2.imshow(WIN, view)
        key = cv2.waitKey(1) & 0xFF
        if key == ord("r"):
            x, y, w, h = cv2.selectROI(WIN, f, showCrosshair=True)
            if w > 3 and h > 3:
                spot = [x, y, x + w, y + h]
                tracker.reset()
                tracker.lock(f, spot)
        elif key == ord("m") and spot:
            spots += 1
            results.append(measure_case(cap, tracker, spot, f"spot {spots}"))
            print(results[-1])
        elif key == ord("p"):
            results.append(measure_people(cap, pose))
            print(results[-1])
        elif key in (ord("q"), 27):
            break

    cap.release()
    cv2.destroyAllWindows()
    if results:
        block = f"\n## Corner check {datetime.now():%Y-%m-%d %H:%M} (camera {args.camera})\n\n" + "\n".join(f"- {r}" for r in results) + "\n"
        with open(ROOT / "NOTES.md", "a") as fh:
            fh.write(block)
        print(block + f"\nAppended to {ROOT / 'NOTES.md'}")


if __name__ == "__main__":
    main()
