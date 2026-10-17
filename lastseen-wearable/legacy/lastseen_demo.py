"""
Last Seen — single-item webcam demo.

Flow:
  1. Hold your AirPods up to the webcam and press SPACE (auto-lock) or R (draw a box).
  2. The tracker locks on and follows the case. It never forgets: when the case
     can't be seen, it keeps the last place it was confidently seen.
  3. Put the case somewhere behind you. Wait.
  4. Say "Where are my AirPods?" (or press W). The demo saves a screenshot with
     the spot highlighted, shows it full size, and answers out loud.

Keys: SPACE lock  R draw box  W ask  D toggle debug  U unlock  Q quit
"""

import argparse
import queue
import re
import subprocess
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[1]  # repo root (this file lives in legacy/)
MODELS = ROOT / "models"
ANSWERS = ROOT / "answers"

import ultralytics.nn.text_model as _text_model  # noqa: E402

# Keep YOLO-World's CLIP text encoder in models/ instead of ./weights.
_text_model.WEIGHTS_DIR = MODELS

import clip  # noqa: E402
from ultralytics import YOLOWorld  # noqa: E402

# YOLO-World barely knows "airpods case" (scores ~0.01), but it boxes the case under classes it does know,
# like "cell phone" and "remote". These prompts only propose boxes; CLIP decides which one is ours.
PROMPTS = ["airpods case", "white earbuds case", "small white plastic case", "earbuds",
           "cell phone", "remote", "white box"]
DEVICE = "mps" if torch.backends.mps.is_available() else "cpu"
WIN = "Last Seen"
DET_CONF = 0.001  # the case is proposed far away, but with confidence well under 0.02
DET_IMGSZ = 1280  # at 960, a case ~20 px wide stops being proposed
MAX_DETS = 8  # detections verified with CLIP per frame
# How much more a box must look like our item than like the background. Measured: the case ~20 px wide
# scores +0.06, while the best non-case box in the same scene scores -0.16 or lower.
MARGIN_FOLLOW = 0.02  # while following
MARGIN_REACQUIRE = 0.04  # when picking it back up after losing it
TARGET = 0.4  # SPACE only locks onto something inside the centre target (fraction of frame width/height)
GRACE_FRAMES = 5  # unverified frames to keep following before calling it lost
SMOOTH = 0.6  # weight of the newest box when smoothing the drawn box


def say(text):
    subprocess.Popen(["say", "-r", "175", text])


def iou(a, b):
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0, x2 - x1) * max(0, y2 - y1)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def clamp_box(box, w, h):
    x1, y1, x2, y2 = box
    x1, x2 = max(0, min(w - 1, x1)), max(0, min(w, x2))
    y1, y2 = max(0, min(h - 1, y1)), max(0, min(h, y2))
    return [int(x1), int(y1), int(max(x1 + 2, x2)), int(max(y1 + 2, y2))]


class LatestFrame(threading.Thread):
    """Reads the camera on its own thread and keeps only the newest frame, so we never show a stale, buffered one."""

    def __init__(self, cap):
        super().__init__(daemon=True)
        self.cap = cap
        self.frame = None
        self.seq = 0
        self.cond = threading.Condition()

    def run(self):
        while True:
            ok, frame = self.cap.read()
            if not ok:
                time.sleep(0.005)
                continue
            with self.cond:
                self.frame, self.seq = frame, self.seq + 1
                self.cond.notify_all()

    def read(self, after_seq):
        """Waits for a frame newer than after_seq and returns (seq, frame)."""
        with self.cond:
            self.cond.wait_for(lambda: self.seq > after_seq, timeout=1.0)
            return self.seq, self.frame


class Embedder:
    """CLIP image embeddings, used to check that a box really is *our* AirPods."""

    def __init__(self):
        self.model, self.preprocess = clip.load("ViT-B/32", device=DEVICE, download_root=str(MODELS / "clip"))
        self.model.eval()

    @torch.no_grad()
    def embed(self, frame, boxes):
        if not boxes:
            return np.zeros((0, 512), dtype=np.float32)
        from PIL import Image

        crops = []
        h, w = frame.shape[:2]
        for b in boxes:
            x1, y1, x2, y2 = b
            # A little context around the box helps CLIP with tiny objects.
            pad = int(0.15 * max(x2 - x1, y2 - y1))
            x1, y1, x2, y2 = clamp_box([x1 - pad, y1 - pad, x2 + pad, y2 + pad], w, h)
            crop = cv2.cvtColor(frame[y1:y2, x1:x2], cv2.COLOR_BGR2RGB)
            crops.append(self.preprocess(Image.fromarray(crop)))
        feats = self.model.encode_image(torch.stack(crops).to(DEVICE)).float()
        feats = feats / feats.norm(dim=-1, keepdim=True)
        return feats.cpu().numpy()


class SpeechListener(threading.Thread):
    """Listens to the mic in short chunks and fires when it hears 'where ... airpods'."""

    def __init__(self, on_ask):
        super().__init__(daemon=True)
        self.on_ask = on_ask
        self.status = "starting mic"

    def run(self):
        try:
            import sounddevice as sd
            from faster_whisper import WhisperModel
        except Exception as e:  # pragma: no cover
            self.status = f"voice off ({e})"
            return
        model = WhisperModel("base.en", device="cpu", compute_type="int8", download_root=str(MODELS / "whisper"))
        sr, chunk = 16000, 3.0
        audio_q = queue.Queue()
        buf = deque(maxlen=int(sr * 4.5))  # rolling window so a phrase split across chunks still matches

        def cb(indata, frames, t, status):
            audio_q.put(indata[:, 0].copy())

        try:
            stream = sd.InputStream(samplerate=sr, channels=1, dtype="float32", callback=cb, blocksize=int(sr * 0.25))
            stream.start()
        except Exception as e:
            self.status = f"voice off ({e})"
            return
        self.status = "listening"
        last_fire, since = 0.0, 0
        while True:
            block = audio_q.get()
            buf.extend(block)
            since += len(block)
            if since < sr * 1.5:
                continue
            since = 0
            audio = np.array(buf, dtype=np.float32)
            if np.sqrt(np.mean(audio**2)) < 0.005:  # silence
                continue
            segs, _ = model.transcribe(audio, language="en", beam_size=1, vad_filter=True)
            text = " ".join(s.text for s in segs).lower()
            if text.strip():
                self.status = f'heard: "{text.strip()[:50]}"'
            if re.search(r"air ?pods?|ear ?pods?|earbuds?|headphones", text) and re.search(r"where|find|seen|lost", text):
                if time.time() - last_fire > 6:
                    last_fire = time.time()
                    buf.clear()
                    self.on_ask()


class Tracker:
    """One locked-on object. Combines YOLO-World detections, a CSRT tracker, and CLIP re-identification."""

    def __init__(self, detector, embedder, sim_thresh):
        self.det = detector
        self.emb = embedder
        self.sim_thresh = sim_thresh
        self.reset()

    def reset(self):
        self.locked = False
        self.gallery = None  # enrolled appearance embeddings
        self.negatives = None  # background patches it must NOT match
        self.template = None
        self.csrt = None
        self.box = None  # current box (None when not visible)
        self.sim = 0.0
        self.last_seen = None  # dict(box, frame, time, sim)
        self.missing_since = None
        self.misses = 0  # consecutive frames that failed verification
        self.shown = None  # smoothed box for drawing

    # -- detection helpers -------------------------------------------------
    def detect(self, frame, conf):
        r = self.det.predict(frame, conf=conf, verbose=False, device=DEVICE, imgsz=DET_IMGSZ)[0]
        h, w = frame.shape[:2]
        out = []
        for b in r.boxes:
            box = clamp_box(b.xyxy[0].tolist(), w, h)
            area = (box[2] - box[0]) * (box[3] - box[1])
            if area < 0.25 * w * h:  # ignore huge boxes (people, walls)
                out.append((box, float(b.conf)))
        return out

    def template_candidates(self, frame, k=3):
        """Multi-scale template match against the enrolled crop, for when the detector misses."""
        if self.template is None:
            return []
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        th, tw = self.template.shape[:2]
        h, w = gray.shape
        cands = []
        for s in (0.15, 0.25, 0.35, 0.5, 0.7, 1.0, 1.3):
            t = cv2.resize(self.template, (max(8, int(tw * s)), max(8, int(th * s))))
            if t.shape[0] >= h or t.shape[1] >= w:
                continue
            res = cv2.matchTemplate(gray, t, cv2.TM_CCOEFF_NORMED)
            for _ in range(k):
                _, mv, _, ml = cv2.minMaxLoc(res)
                cands.append(([ml[0], ml[1], ml[0] + t.shape[1], ml[1] + t.shape[0]], mv))
                cv2.rectangle(res, (ml[0] - t.shape[1] // 2, ml[1] - t.shape[0] // 2),
                              (ml[0] + t.shape[1] // 2, ml[1] + t.shape[0] // 2), -1, -1)
        cands.sort(key=lambda c: -c[1])
        return [c[0] for c in cands[:k]]

    def similarity(self, frame, boxes):
        """Returns (similarity to our item, how much more it looks like our item than the background)."""
        if not boxes:
            return np.zeros(0), np.zeros(0)
        e = self.emb.embed(frame, boxes)
        pos = (e @ self.gallery.T).max(axis=1)
        neg = (e @ self.negatives.T).max(axis=1)
        return pos, pos - neg

    def _negatives(self, frame, box, n=12):
        """Sample background patches (and look-alike detections) away from the item."""
        h, w = frame.shape[:2]
        bw, bh = box[2] - box[0], box[3] - box[1]
        rng = np.random.default_rng(0)
        boxes = [b for b, _ in self.detect(frame, conf=DET_CONF) if iou(b, box) < 0.1]
        while len(boxes) < n:
            s = rng.uniform(0.6, 1.6)
            x = rng.uniform(0, max(1, w - bw * s))
            y = rng.uniform(0, max(1, h - bh * s))
            b = clamp_box([x, y, x + bw * s, y + bh * s], w, h)
            if iou(b, box) < 0.05:
                boxes.append(b)
        return self.emb.embed(frame, boxes[: n + 6])

    # -- locking -----------------------------------------------------------
    def lock(self, frame, box):
        h, w = frame.shape[:2]
        box = clamp_box(box, w, h)
        self.gallery = self.emb.embed(frame, [box])
        self.negatives = self._negatives(frame, box)
        x1, y1, x2, y2 = box
        self.template = cv2.cvtColor(frame[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)
        self.locked = True
        self._start_csrt(frame, box)
        self.box, self.sim = box, 1.0
        self._mark_seen(frame, box, 1.0)

    def auto_lock(self, frame):
        """Lock onto the most confident detection inside the centre target. Boxes outside it or touching
        the frame edge (an elbow, the table) are never candidates."""
        h, w = frame.shape[:2]
        tx1, ty1, tx2, ty2 = target_box(w, h)
        inside = [(b, c) for b, c in self.detect(frame, conf=DET_CONF)
                  if tx1 <= (b[0] + b[2]) / 2 <= tx2 and ty1 <= (b[1] + b[3]) / 2 <= ty2
                  and b[0] > 2 and b[1] > 2 and b[2] < w - 2 and b[3] < h - 2
                  and (b[2] - b[0]) < (tx2 - tx1) and (b[3] - b[1]) < (ty2 - ty1)]
        if not inside:
            return None
        box = max(inside, key=lambda d: d[1])[0]
        self.lock(frame, box)
        return box

    def _start_csrt(self, frame, box):
        self.csrt = cv2.TrackerCSRT_create()
        x1, y1, x2, y2 = box
        self.csrt.init(frame, (x1, y1, x2 - x1, y2 - y1))

    def _mark_seen(self, frame, box, sim):
        self.last_seen = {"box": box, "frame": frame.copy(), "time": time.time(), "sim": sim}
        self.missing_since = None

    # -- per-frame update ----------------------------------------------------
    def update(self, frame, frame_idx):
        if not self.locked:
            return
        h, w = frame.shape[:2]
        cands = []

        # 1) CSRT follows the object frame to frame.
        if self.csrt is not None:
            ok, (x, y, bw, bh) = self.csrt.update(frame)
            if ok and bw > 2 and bh > 2:
                cands.append(("track", clamp_box([x, y, x + bw, y + bh], w, h), 0.0))

        # 2) YOLO-World proposes case-like boxes anywhere in the frame. CLIP cost grows with every box,
        #    so keep the most confident few plus anything overlapping where the item was.
        prev = self.box or (self.last_seen and self.last_seen["box"])
        dets = sorted(self.detect(frame, conf=DET_CONF), key=lambda d: -d[1])
        near = [d for d in dets[MAX_DETS:] if prev is not None and iou(d[0], prev) > 0.1]
        for box, c in dets[:MAX_DETS] + near[:2]:
            cands.append(("det", box, c))

        # 3) When we've lost it for a bit, also scan with the template (slow, so not every frame).
        if self.box is None and frame_idx % 6 == 0:
            for box in self.template_candidates(frame):
                cands.append(("tmpl", box, 0.0))

        if not cands:
            self._lost()
            return

        sims, margins = self.similarity(frame, [c[1] for c in cands])
        best, best_score, best_sim, best_margin = None, -1e9, 0.0, 0.0
        for (src, box, conf), s, m in zip(cands, sims, margins):
            score = s + m + 0.15 * conf
            if prev is not None:
                score += 0.08 * iou(box, prev)  # mild preference for staying put
            if score > best_score:
                best, best_score, best_sim, best_margin = (src, box), score, float(s), float(m)

        # Following it is easy; picking it back up after losing it needs more proof.
        reacquire = self.box is None and not (prev is not None and iou(best[1], prev) > 0.3)
        need = self.sim_thresh + (0.05 if reacquire else 0.0)
        if best_sim >= need and best_margin >= (MARGIN_REACQUIRE if reacquire else MARGIN_FOLLOW):
            src, box = best
            # Re-anchor the tracker on a verified detection only when it has drifted; re-creating it every frame is slow.
            if src != "track" and (self.box is None or iou(box, self.box) < 0.6 or frame_idx % 30 == 0):
                self._start_csrt(frame, box)
            self.box, self.sim, self.misses = box, best_sim, 0
            self._mark_seen(frame, box, best_sim)
            # Learn new views (e.g. lid open, different angle) when we're very sure.
            if best_sim > 0.88 and best_margin > 0.15 and len(self.gallery) < 12 and frame_idx % 15 == 0:
                self.gallery = np.vstack([self.gallery, self.emb.embed(frame, [box])])
        else:
            self.sim = best_sim
            # One bad frame (motion blur, a hand passing) shouldn't drop it: keep following the tracker briefly.
            track = next((c[1] for c in cands if c[0] == "track"), None)
            if self.box is not None and track is not None and self.misses < GRACE_FRAMES:
                self.misses += 1
                self.box = track
            else:
                self._lost()

    def _lost(self):
        self.box = None
        self.misses = 0
        if self.missing_since is None:
            self.missing_since = time.time()

    def display_box(self):
        """Box smoothed over time for drawing, so it glides instead of jittering. Snaps on big jumps."""
        if self.box is None:
            self.shown = None
            return None
        if self.shown is None or iou(self.shown, self.box) < 0.3:
            self.shown = [float(v) for v in self.box]
        else:
            self.shown = [SMOOTH * b + (1 - SMOOTH) * s for b, s in zip(self.box, self.shown)]
        return [int(round(v)) for v in self.shown]


def target_box(w, h):
    """The centre region SPACE locks inside; drawn on screen while unlocked."""
    return [int(w * (0.5 - TARGET / 2)), int(h * (0.5 - TARGET / 2)), int(w * (0.5 + TARGET / 2)), int(h * (0.5 + TARGET / 2))]


def describe_location(box, frame_shape, person_box):
    h, w = frame_shape[:2]
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    # The webcam image isn't mirrored: your left is the right side of the image.
    if person_box is not None and person_box[0] < cx < person_box[2] and cy < person_box[3]:
        side = "right behind you"
    elif person_box is not None and cx > person_box[2]:
        side = "behind you, to your left"
    elif person_box is not None and cx < person_box[0]:
        side = "behind you, to your right"
    else:
        side = "to your left" if cx > w / 2 else "to your right"
    height = "up high" if cy < h * 0.33 else ("down low" if cy > h * 0.7 else "")
    return f"{side} {height}".strip()


def ago(seconds):
    s = int(seconds)
    if s < 10:
        return "just now"
    if s < 60:
        return f"{s} seconds ago"
    m = s // 60
    return f"{m} minute{'s' if m != 1 else ''} ago"


def render_answer(frame, box, label, sub):
    img = frame.copy()
    dim = (img * 0.45).astype(np.uint8)
    x1, y1, x2, y2 = box
    cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
    r = int(max(x2 - x1, y2 - y1) * 0.9) + 20
    mask = np.zeros(img.shape[:2], np.uint8)
    cv2.circle(mask, (cx, cy), r, 255, -1)
    img = np.where(mask[..., None] > 0, img, dim)  # spotlight
    cv2.circle(img, (cx, cy), r, (0, 220, 255), 4, cv2.LINE_AA)
    cv2.circle(img, (cx, cy), r + 10, (0, 220, 255), 1, cv2.LINE_AA)
    cv2.rectangle(img, (x1, y1), (x2, y2), (0, 255, 120), 2, cv2.LINE_AA)
    h, w = img.shape[:2]
    cv2.rectangle(img, (0, h - 110), (w, h), (20, 20, 20), -1)
    cv2.putText(img, label, (24, h - 62), cv2.FONT_HERSHEY_DUPLEX, 1.4, (255, 255, 255), 2, cv2.LINE_AA)
    cv2.putText(img, sub, (24, h - 24), cv2.FONT_HERSHEY_SIMPLEX, 0.85, (200, 200, 200), 2, cv2.LINE_AA)
    return img


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--camera", type=int, default=0)
    ap.add_argument("--sim", type=float, default=0.70,
                    help="CLIP similarity needed to count as 'seen' (a case ~20 px wide scores ~0.79; the margin check guards against look-alikes)")
    ap.add_argument("--item", default="AirPods")
    ap.add_argument("--no-voice", action="store_true")
    args = ap.parse_args()

    ANSWERS.mkdir(exist_ok=True)
    print(f"Loading models on {DEVICE}...")
    detector = YOLOWorld(str(MODELS / "yolov8s-worldv2.pt"))
    detector.set_classes(PROMPTS)
    person_det = YOLOWorld(str(MODELS / "yolov8s-worldv2.pt"))
    person_det.set_classes(["person"])
    tracker = Tracker(detector, Embedder(), args.sim)

    cap = cv2.VideoCapture(args.camera)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    if not cap.isOpened():
        raise SystemExit("Couldn't open the webcam. Allow camera access for your terminal in System Settings > Privacy.")
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    camera = LatestFrame(cap)
    camera.start()
    seq = 0

    ask_flag = threading.Event()
    listener = None
    if not args.no_voice:
        listener = SpeechListener(ask_flag.set)
        listener.start()

    cv2.namedWindow(WIN, cv2.WINDOW_NORMAL)
    debug, frame_idx, fps_t, fps = True, 0, time.time(), 0.0
    answer_until, answer_img = 0, None
    person_box = None

    while True:
        new_seq, frame = camera.read(seq)
        if frame is None or new_seq == seq:
            cv2.waitKey(1)
            continue
        seq = new_seq
        frame_idx += 1
        tracker.update(frame, frame_idx)

        if frame_idx % 10 == 0:
            ppl = person_det.predict(frame, conf=0.3, verbose=False, device=DEVICE)[0].boxes
            person_box = max((b.xyxy[0].tolist() for b in ppl), key=lambda b: (b[2] - b[0]) * (b[3] - b[1]), default=None)

        # ---- the ask ----
        if ask_flag.is_set():
            ask_flag.clear()
            if not tracker.locked or tracker.last_seen is None:
                say(f"I haven't been shown your {args.item} yet.")
            else:
                visible = tracker.box is not None
                seen = tracker.last_seen
                shot = frame if visible else seen["frame"]
                box = tracker.box if visible else seen["box"]
                where = describe_location(box, shot.shape, person_box)
                stamp = datetime.fromtimestamp(seen["time"]).strftime("%-I:%M:%S %p")
                if visible:
                    speech = f"Your {args.item} are {where}."
                    sub = f"Visible right now - {where}"
                else:
                    speech = f"I can't see your {args.item} right now. I last saw them {where}, {ago(time.time() - seen['time'])}."
                    sub = f"Last seen {stamp} - {where}"
                answer_img = render_answer(shot, box, f"Your {args.item}", sub)
                path = ANSWERS / f"answer_{datetime.now():%H%M%S}.jpg"
                cv2.imwrite(str(path), answer_img)
                print(f"[ask] {speech}  -> {path}")
                say(speech)
                answer_until = time.time() + 8

        # ---- draw ----
        view = frame.copy()
        if tracker.locked:
            shown = tracker.display_box()
            if shown is not None:
                x1, y1, x2, y2 = shown
                cv2.rectangle(view, (x1, y1), (x2, y2), (0, 255, 120), 3, cv2.LINE_AA)
                cv2.putText(view, f"{args.item}  {tracker.sim:.2f}", (x1, max(20, y1 - 10)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 120), 2, cv2.LINE_AA)
            elif tracker.last_seen is not None:
                x1, y1, x2, y2 = tracker.last_seen["box"]
                cv2.rectangle(view, (x1, y1), (x2, y2), (0, 200, 255), 2, cv2.LINE_4)
                cv2.putText(view, f"last seen {ago(time.time() - tracker.last_seen['time'])}", (x1, max(20, y1 - 10)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 200, 255), 2, cv2.LINE_AA)
            status = f"LOCKED on {args.item}" + ("" if tracker.box is not None else "  (not visible - holding last seen)")
        else:
            status = f"Hold your {args.item} inside the box and press SPACE (or R to draw a box)"
            tx1, ty1, tx2, ty2 = target_box(view.shape[1], view.shape[0])
            cv2.rectangle(view, (tx1, ty1), (tx2, ty2), (255, 255, 255), 2, cv2.LINE_AA)
        now = time.time()
        fps = 0.9 * fps + 0.1 / max(1e-3, now - fps_t)
        fps_t = now
        cv2.rectangle(view, (0, 0), (view.shape[1], 36), (20, 20, 20), -1)
        cv2.putText(view, status, (12, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA)
        if debug:
            info = f"{fps:4.1f} fps  sim {tracker.sim:.2f}/{args.sim}  voice: {listener.status if listener else 'off'}  [W ask, D debug, U unlock, Q quit]"
            cv2.putText(view, info, (12, view.shape[0] - 14), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)

        cv2.imshow(WIN, answer_img if (answer_img is not None and now < answer_until) else view)
        key = cv2.waitKey(1) & 0xFF
        if key in (ord("q"), 27):
            break
        elif key == ord(" "):
            box = tracker.auto_lock(frame)
            print("[lock]", box if box else "nothing found inside the centre box - move it closer to the middle, or press R")
            if box:
                say(f"Got it. Tracking your {args.item}.")
        elif key == ord("r"):
            x, y, bw, bh = cv2.selectROI(WIN, frame, showCrosshair=True)
            if bw > 4 and bh > 4:
                tracker.lock(frame, [x, y, x + bw, y + bh])
                say(f"Got it. Tracking your {args.item}.")
        elif key == ord("w"):
            ask_flag.set()
        elif key == ord("u"):
            tracker.reset()
        elif key == ord("d"):
            debug = not debug
        elif key in (13, 10) and now < answer_until:
            answer_until = 0

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
