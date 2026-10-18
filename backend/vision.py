"""Camera capture + YOLO tracking + motion analysis in a background thread.

Frames live in memory only (a short ring buffer for picking snapshot frames). Confirmed events
from SpatialMemory are handed to SnapshotStore, which writes selected photos on its own thread.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
import threading
import time
from collections import deque

import cv2
import numpy as np

from cameras import find_camera, list_cameras
from catalog import MIN_CONF, SUPPORTED
from memory import ALIASES, ItemMemory, Observation, display_name
from presence import PresenceTracker
from snapshots import SnapshotStore
from wearable import Hand, InteractionDetector, WearableObserver
import events as E

PHOTO_EVENTS = {E.OBJECT_OBSERVED, E.PLACEMENT_CONFIRMED}  # observation events that keep a photo

# Classes in items.pt with no real training photos yet: leave these to YOLO-World.
NOT_TRAINED: set = set()  # all 4 custom classes trained (glasses mAP50 0.99)

log = logging.getLogger("keepsake.vision")

PERSON = "person"  # detected to judge occlusion and whether someone is in the room
# YOLO-World also looks for hands: from a chest mount they're usually partial, at the bottom edge,
# where MediaPipe (which needs most of a hand) rarely fires. Both sources are merged.
HAND = "hand"
HAND_CONF = float(os.getenv("CTRLF_HAND_CONF", "0.2"))


def pick_device() -> str:
    """Use the GPU when there is one (Apple MPS or CUDA); 1280-wide detection is ~3x faster."""
    try:
        import torch
        if torch.cuda.is_available():
            return "cuda"
        if torch.backends.mps.is_available():
            return "mps"
    except Exception:  # noqa: BLE001
        pass
    return "cpu"


class MotionDetector:
    """Frame differencing on a small blurred grayscale image."""

    def __init__(self, width: int = 160, threshold: int = 25):
        self.width = width
        self.threshold = threshold
        self._prev: np.ndarray | None = None
        self.mask: np.ndarray | None = None

    def update(self, frame: np.ndarray) -> float:
        h, w = frame.shape[:2]
        small = cv2.resize(frame, (self.width, max(1, int(h * self.width / w))))
        gray = cv2.GaussianBlur(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY), (5, 5), 0)
        if self._prev is None or self._prev.shape != gray.shape:
            self._prev, self.mask = gray, np.zeros_like(gray, dtype=bool)
            return 0.0
        self.mask = cv2.absdiff(gray, self._prev) > self.threshold
        self._prev = gray
        return float(self.mask.mean())

    def local(self, bbox: tuple[float, float, float, float], pad: float = 0.15) -> float:
        if self.mask is None:
            return 0.0
        h, w = self.mask.shape
        x0, y0, x1, y1 = bbox
        px, py = (x1 - x0) * pad, (y1 - y0) * pad
        c0, c1 = int(max(0, x0 - px) * w), int(min(1, x1 + px) * w) + 1
        r0, r1 = int(max(0, y0 - py) * h), int(min(1, y1 + py) * h) + 1
        roi = self.mask[r0:r1, c0:c1]
        return float(roi.mean()) if roi.size else 0.0

    def background(self, exclude: list[tuple[float, float, float, float]], pad: float = 0.1) -> float:
        """Changed-pixel fraction outside the given boxes (hands, objects): camera motion, not
        the motion of a hand moving an object."""
        if self.mask is None:
            return 0.0
        h, w = self.mask.shape
        keep = np.ones_like(self.mask, dtype=bool)
        for x0, y0, x1, y1 in exclude:
            px, py = (x1 - x0) * pad, (y1 - y0) * pad
            keep[int(max(0, y0 - py) * h):int(min(1, y1 + py) * h) + 1,
                 int(max(0, x0 - px) * w):int(min(1, x1 + px) * w) + 1] = False
        return float(self.mask[keep].mean()) if keep.any() else 0.0


def merge_hands(primary: list[Hand], extra: list[Hand], same: float = 0.3) -> list[Hand]:
    """MediaPipe hands plus YOLO-World hand boxes that don't overlap one of them."""
    def iou(a, b):
        ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
        iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
        inter = ix * iy
        union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
        return inter / union if union > 0 else 0.0
    return list(primary) + [h for h in extra if all(iou(h.bbox, p.bbox) < same for p in primary)]


class VisionWorker(threading.Thread):
    def __init__(self, memory: ItemMemory, snapshots: SnapshotStore, camera_index: int | str = 0,
                 model_path: str = "yolov8s-worldv2.pt", conf: float = 0.15, fps: float = 5.0,
                 frame_width: int = 1280, device: str | None = None, preview_width: int = 640,
                 presence: PresenceTracker | None = None, camera_name: str | None = None,
                 hands_enabled: bool = True, frozen_seconds: float = 5.0, verify_enabled: bool = True):
        super().__init__(daemon=True, name="vision")
        self.memory = memory
        self.snapshots = snapshots
        self.camera_index = camera_index
        self.camera_name = camera_name  # e.g. "iPhone": wins over camera_index (see cameras.py)
        self.model_path = model_path
        self._label: dict[str, str] = {}  # YOLO-World prompt -> catalog category
        self.conf = conf
        self.interval = 1.0 / max(fps, 0.5)
        self.frame_width = frame_width  # detection resolution; small items across a room need ~1280
        self.preview_width = preview_width
        self.device = device or pick_device()
        self.motion = MotionDetector()
        self.presence = presence or PresenceTracker()
        self.observer = WearableObserver("wearable")             # issue #4: object_observed
        self.interactions = InteractionDetector("wearable")      # issue #5: hand evidence
        self.hands_enabled = hands_enabled
        self.hands = None  # hands.HandDetector, created on the worker thread
        self.verify_enabled = verify_enabled
        self.verifier = None  # verify.ClipVerifier: second opinion on every item box
        self._ring: deque[tuple[int, np.ndarray]] = deque(maxlen=12)  # (frame_id, snapshot-size frame)
        self._frame_id = 0
        self._still_frames = 0  # consecutive frames with exactly zero change: a frozen feed
        self._frozen_frames = max(1, int(frozen_seconds * fps))
        self._halt = threading.Event()
        self._jpeg: bytes | None = None
        self._jpeg_id = 0
        self._jpeg_lock = threading.Lock()
        self.status = {"camera": "starting", "error": None, "warning": None, "fps": 0.0,
                       "device": self.device, "inference_width": frame_width,
                       "motion": 0.0, "detections": [], "model": model_path,
                       "camera_mode": "wearable", "camera_motion": 0.0,
                       "hands": "off", "hands_reason": None, "interactions": {},
                       "verify": "off", "verify_dropped": 0,
                       **self.presence.status()}

    # ---- public ----
    def latest_jpeg(self) -> bytes | None:
        with self._jpeg_lock:
            return self._jpeg

    def latest_frame(self) -> tuple[int, bytes | None]:
        """(frame number, annotated JPEG) of the newest processed frame."""
        with self._jpeg_lock:
            return self._jpeg_id, self._jpeg

    def stop(self) -> None:
        self._halt.set()

    # ---- thread ----
    def run(self) -> None:
        try:
            from ultralytics import YOLO, settings
            settings.update({"sync": False})  # no Ultralytics telemetry
            model = YOLO(self.model_path)
            # Optional model trained on our own items (last-seen/train.py -> models/items.pt).
            # It handles the items it knows; YOLO-World keeps looking for everything else.
            self._items_model = None
            items_path = Path(os.getenv("CTRLF_ITEMS_MODEL", str(Path(__file__).parent / "models" / "items.pt")))
            if items_path.exists():
                self._items_model = YOLO(str(items_path))
                log.info("custom items model %s: %s", items_path.name, list(self._items_model.names.values()))
            custom = (set(self._items_model.names.values()) - NOT_TRAINED) if self._items_model else set()
            if self.verify_enabled:
                from verify import ClipVerifier
                self.verifier = ClipVerifier(self.device)
                self.status.update(verify="on" if self.verifier.available else "unavailable")
            # With the CLIP check catching look-alikes, YOLO-World also proposes the trained items as a
            # backup (it found a real wallet the trained model missed); without it, it skips them.
            verified = self.verifier is not None and self.verifier.available
            if "world" in str(self.model_path).lower():  # open vocabulary: tell it what to look for
                from catalog import CATALOG
                try:
                    model.set_classes([c for c in SUPPORTED if verified or c not in custom] + [PERSON, HAND])
                except ImportError as e:  # YOLO-World encodes the prompts with CLIP
                    raise RuntimeError(
                        "YOLO-World needs CLIP: run .venv/bin/pip install -r backend/requirements.txt") from e
                self._label = {c.get("prompt", c["category"]): c["category"] for c in CATALOG}
        except Exception as e:  # noqa: BLE001
            log.exception("model load failed")
            self.status.update(camera="error", error=f"Model load failed: {e}")
            return
        class_ids = [i for i, n in model.names.items()
                     if self._label.get(n, n) in ALIASES or n in (PERSON, HAND)]
        self._yolo_hands = HAND in model.names.values()
        seen_names = {self._label.get(n, n) for n in model.names.values()}
        missing = [c for c in ALIASES if c not in seen_names and c not in custom]
        if missing:  # e.g. a COCO-only model can't see keys or wallets
            log.warning("detector %s can't detect: %s", self.model_path, ", ".join(missing))
        self.status["undetectable"] = missing
        if self.hands_enabled:
            from hands import HandDetector
            self.hands = HandDetector()
            self.status.update(hands="on" if self.hands.available else "unavailable",
                               hands_reason=self.hands.reason or None)
        else:
            self.status["hands_reason"] = "disabled (CTRLF_HANDS=0)"

        cap = None
        failures = 0
        while not self._halt.is_set():
            if cap is None or not cap.isOpened():
                cap = self._open_camera()
                if cap is None:
                    self._halt.wait(3.0)
                    continue
            t0 = time.monotonic()
            ok, raw = cap.read()
            if (not ok or raw is None) and isinstance(self.camera_index, str):
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)  # loop test video files
                ok, raw = cap.read()
            if not ok or raw is None:
                # Cameras (esp. macOS / Continuity Camera) return empty frames while warming up;
                # only reopen after a sustained run of failures.
                failures += 1
                if failures >= 50:
                    self.status.update(camera="error", error="Camera read failed; reopening")
                    cap.release()
                    cap = None
                    failures = 0
                    self._halt.wait(2.0)
                else:
                    self._halt.wait(0.1)
                continue
            failures = 0
            if self.status["camera"] != "active":
                self.status.update(camera="active", error=None)
            self._process(model, class_ids, raw)
            elapsed = time.monotonic() - t0
            self.status["fps"] = round(1.0 / max(elapsed, self.interval), 1)
            self._halt.wait(max(0.0, self.interval - elapsed))
        if cap is not None:
            cap.release()
        self.status["camera"] = "stopped"

    def _process(self, model, class_ids: list[int], raw: np.ndarray) -> None:
        self._frame_id += 1
        full = self._resize(raw, self.snapshots.max_width)
        frame = self._resize(full, self.frame_width)
        self._ring.append((self._frame_id, full))

        global_motion = self.motion.update(frame)
        self.status["motion"] = round(global_motion, 3)
        # Real sensors always have some noise; exactly zero change for seconds is a frozen feed
        # (Continuity Camera pauses while the iPhone is unlocked or in use).
        self._still_frames = self._still_frames + 1 if global_motion == 0.0 else 0
        warning = None
        if float(frame[::8, ::8].mean()) < 8:  # e.g. Continuity Camera paused or lens covered
            warning = "The camera is sending black frames. Check the lens isn't covered."
        elif self._still_frames >= self._frozen_frames:
            warning = ("The camera picture is frozen. If it's an iPhone, lock it and keep it still "
                       "so Continuity Camera resumes.")
        self.status["warning"] = warning

        hands = []
        try:
            obs = self._detect(model, frame, class_ids) + self._detect_items(frame)
            if self.verifier is not None:
                before = len(obs)
                obs = self.verifier.keep(frame, obs)
                self.status["verify_dropped"] = before - len(obs)
            for o in obs:
                o.motion = self.motion.local(o.bbox)
            if self.presence.update(obs) == "left":
                log.info("person left the view")
            self.status.update(self.presence.status())
            for ev in self.memory.observe(obs, frame_id=self._frame_id):
                log.info("%s %s", ev["event_type"], ev["name"])  # photos come from observation events
            mp_hands = self.hands.detect(frame) if self.hands else []
            hands = merge_hands(mp_hands, [Hand(o.bbox, o.confidence) for o in obs
                                           if o.category == HAND and o.confidence >= HAND_CONF])
            self.status["hands_in_view"] = {"mediapipe": len(mp_hands), "total": len(hands)}
            self._observe_wearable([o for o in obs if o.category != HAND], hands)
        except Exception as e:  # noqa: BLE001
            log.exception("inference failed")
            if self.device != "cpu":  # e.g. an MPS op that isn't supported: fall back for good
                log.warning("falling back to CPU inference")
                self.device = self.status["device"] = "cpu"
                model.predictor = None
            self.status["error"] = f"Detection error: {e}"
            obs = []
        shown = [o for o in obs if o.category in MIN_CONF and o.confidence >= MIN_CONF[o.category]]
        people = [o for o in obs if o.category == PERSON and o.confidence >= self.presence.min_conf]
        self._publish(self._resize(frame, self.preview_width), shown, people, hands)  # only what's counted

    def _observe_wearable(self, obs: list[Observation], hands) -> None:
        """Issue #4/#5 events: filtered sightings plus hand-object evidence, stored for Photon/voice."""
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        cam = self.motion.background([o.bbox for o in obs if o.bbox] + [h.bbox for h in hands])
        self.status["camera_motion"] = round(cam, 3)
        view = self.memory.view_id
        out = self.observer.update(obs, now, self._frame_id, cam, view)
        if (self.hands is not None and self.hands.available) or getattr(self, "_yolo_hands", False):
            out += self.interactions.update(obs, hands, now, self._frame_id, cam, view)
            self.status["interactions"] = {c: s for c, s in self.interactions.states().items() if s != "IDLE"}
        for ev in out:
            self._record(ev)

    def _record(self, ev: dict) -> None:
        db = self.memory.db
        db.add_observation(ev)
        log.info("%s %s (%.2f) %s", ev["event_type"], ev["name"], ev["confidence"], ",".join(ev["evidence"]))
        if ev["event_type"] in PHOTO_EVENTS:
            photo = {"object_id": ev["object_id"], "event_type": ev["event_type"],
                     "timestamp": ev["timestamp"], "bbox": ev["bbox"], "region": None,
                     "confidence": ev["confidence"], "view_id": ev["view_id"]}
            self.snapshots.submit(photo, self._frame_for(ev["frame_id"]),
                                  on_saved=lambda sid, eid=ev["event_id"]: db.set_observation_snapshot(eid, sid))

    def _frame_for(self, frame_id: int | None) -> np.ndarray | None:
        for fid, f in reversed(self._ring):
            if fid == frame_id:
                return f
        return None

    def _open_camera(self):
        index = self.camera_index
        if self.camera_name:  # indexes shift as cameras come and go; never fall back to another one
            found = find_camera(self.camera_name)
            if found is None:
                names = ", ".join(n for _, n in list_cameras()) or "none"
                self.status.update(camera="error", error=(
                    f"Camera \"{self.camera_name}\" isn't connected (cameras now: {names}). "
                    "For an iPhone: lock it, keep it still near the Mac, and wait."))
                return None
            index = found
        cap = cv2.VideoCapture(index)
        if not cap.isOpened():
            cap.release()
            self.status.update(camera="error", error=(
                f"Can't open camera {index}. Check the camera index and permission."))
            return None
        self.status.update(camera="active", error=None)
        log.info("camera %s opened%s", index, f" ({self.camera_name})" if self.camera_name else "")
        return cap

    @staticmethod
    def _resize(frame: np.ndarray, width: int) -> np.ndarray:
        h, w = frame.shape[:2]
        if w > width:
            frame = cv2.resize(frame, (width, int(h * width / w)))
        return frame

    @staticmethod
    def _encode(frame: np.ndarray, quality: int = 75) -> bytes | None:
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
        return buf.tobytes() if ok else None

    def _detect(self, model, frame: np.ndarray, class_ids: list[int]) -> list[Observation]:
        res = model.track(frame, persist=True, tracker=str(Path(__file__).parent / "tracker_lowconf.yaml") if "world" in str(self.model_path).lower() else "bytetrack.yaml", conf=self.conf,
                          imgsz=self.frame_width, device=self.device,
                          classes=class_ids, verbose=False)[0]
        h, w = frame.shape[:2]
        obs: list[Observation] = []
        if res.boxes is None:
            return obs
        ids = res.boxes.id.int().tolist() if res.boxes.id is not None else [None] * len(res.boxes)
        for xyxy, cls, cf, tid in zip(res.boxes.xyxy.tolist(), res.boxes.cls.int().tolist(),
                                      res.boxes.conf.tolist(), ids):
            x0, y0, x1, y1 = xyxy[0] / w, xyxy[1] / h, xyxy[2] / w, xyxy[3] / h
            obs.append(Observation(category=self._label.get(model.names[cls], model.names[cls]), confidence=float(cf),
                                   x=(x0 + x1) / 2, y=(y0 + y1) / 2, track_id=tid,
                                   bbox=(x0, y0, x1, y1)))
        return obs

    def _detect_items(self, frame: np.ndarray) -> list[Observation]:
        """Detections from our own trained model (keys, wallet, AirPods, glasses)."""
        m = getattr(self, "_items_model", None)
        if m is None:
            return []
        res = m.predict(frame, conf=0.25, imgsz=640, device=self.device, verbose=False,
                        agnostic_nms=True)[0]  # one label per physical box
        h, w = frame.shape[:2]
        best: dict[str, Observation] = {}  # one physical object per item: keep the strongest box
        for xyxy, cls, cf in zip(res.boxes.xyxy.tolist(), res.boxes.cls.int().tolist(), res.boxes.conf.tolist()):
            name = m.names[cls]
            if name not in ALIASES or name in NOT_TRAINED or (name in best and best[name].confidence >= cf):
                continue
            x0, y0, x1, y1 = xyxy[0] / w, xyxy[1] / h, xyxy[2] / w, xyxy[3] / h
            best[name] = Observation(category=name, confidence=float(cf), x=(x0 + x1) / 2,
                                     y=(y0 + y1) / 2, track_id=None, bbox=(x0, y0, x1, y1))
        return list(best.values())

    def _publish(self, frame: np.ndarray, obs: list[Observation],
                 people: list[Observation] = (), hands=()) -> None:
        h, w = frame.shape[:2]
        out = frame.copy()
        for o, color in [(p, (230, 160, 60)) for p in people] + [(o, (90, 200, 120)) for o in obs]:
            x0, y0, x1, y1 = o.bbox  # people in blue, tracked items in green
            p0, p1 = (int(x0 * w), int(y0 * h)), (int(x1 * w), int(y1 * h))
            cv2.rectangle(out, p0, p1, color, 2)
            label = f"{display_name(o.category)} {o.confidence:.0%}"
            cv2.putText(out, label, (p0[0], max(14, p0[1] - 6)), cv2.FONT_HERSHEY_SIMPLEX,
                        0.5, color, 1, cv2.LINE_AA)
        for hd in hands:  # MediaPipe hands, for checking interaction evidence live
            x0, y0, x1, y1 = hd.bbox
            cv2.rectangle(out, (int(x0 * w), int(y0 * h)), (int(x1 * w), int(y1 * h)), (230, 160, 60), 1)
        jpg = self._encode(out)
        if jpg:
            with self._jpeg_lock:
                self._jpeg = jpg
                self._jpeg_id = self._frame_id
        self.status["detections"] = [
            {"category": o.category, "name": display_name(o.category),
             "confidence": round(o.confidence, 2), "track_id": o.track_id} for o in obs]
