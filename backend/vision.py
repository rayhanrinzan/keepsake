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

from furniture import FURNITURE, propose_regions
from cameras import find_camera, list_cameras
from catalog import MIN_CONF, SUPPORTED
from memory import ALIASES, Observation, SpatialMemory, display_name
from modes import MONITORING, ModeController
from presence import PresenceTracker
from snapshots import SnapshotStore
from spatial import Region, locate
from wearable import InteractionDetector, WearableObserver
import events as E

PHOTO_EVENTS = {E.OBJECT_OBSERVED, E.PLACEMENT_CONFIRMED}  # observation events that keep a photo

# Classes in items.pt with no real training photos yet: leave these to YOLO-World.
NOT_TRAINED: set = set()  # all 4 custom classes trained (glasses mAP50 0.99)

log = logging.getLogger("keepsake.vision")

PERSON = "person"  # detected to judge occlusion and whether someone is in the room


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


class VisionWorker(threading.Thread):
    def __init__(self, memory: SpatialMemory, regions: list[Region], snapshots: SnapshotStore,
                 modes: ModeController, camera_index: int | str = 0, model_path: str = "yolo11n.pt",
                 conf: float = 0.4, fps: float = 5.0, frame_width: int = 1280,
                 camera_shift_motion: float = 0.5, scan_model_path: str | None = None,
                 device: str | None = None, preview_width: int = 640,
                 presence: PresenceTracker | None = None, camera_name: str | None = None,
                 camera_mode: str = "wearable", hands_enabled: bool = True):
        super().__init__(daemon=True, name="vision")
        self.memory = memory
        self.regions = regions  # shared list; updated in place by calibration
        self.snapshots = snapshots
        self.modes = modes
        self.camera_index = camera_index
        self.camera_name = camera_name  # e.g. "iPhone": wins over camera_index (see cameras.py)
        self.model_path = model_path
        self.scan_model_path = scan_model_path  # larger model used only by Scan room
        self._scan_model = None
        self._label: dict[str, str] = {}  # YOLO-World prompt -> catalog category
        self.conf = conf
        self.interval = 1.0 / max(fps, 0.5)
        self.frame_width = frame_width  # detection resolution; small items across a room need ~1280
        self.preview_width = preview_width
        self.device = device or pick_device()
        self.camera_shift_motion = camera_shift_motion
        self.motion = MotionDetector()
        self.presence = presence or PresenceTracker()
        self.camera_mode = camera_mode  # "wearable" (body-worn, always moving) or "fixed"
        self.observer = WearableObserver(camera_mode)            # issue #4: object_observed
        self.interactions = InteractionDetector(camera_mode)     # issue #5: hand evidence
        self.hands_enabled = hands_enabled
        self.hands = None  # hands.HandDetector, created on the worker thread
        self._ring: deque[tuple[int, np.ndarray]] = deque(maxlen=12)  # (frame_id, snapshot-size frame)
        self._frame_id = 0
        self._shift_frames = 0
        self._halt = threading.Event()
        self._jpeg: bytes | None = None
        self._jpeg_id = 0
        self._jpeg_lock = threading.Lock()
        self.status = {"camera": "starting", "error": None, "warning": None, "fps": 0.0,
                       "device": self.device, "inference_width": frame_width,
                       "motion": 0.0, "detections": [], "model": model_path,
                       "camera_mode": camera_mode, "camera_motion": 0.0,
                       "hands": "off", "hands_reason": None, "interactions": {},
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
            self.memory.loose_categories = custom  # trained-model boxes wobble more than tracked ones
            if "world" in str(self.model_path).lower():  # open vocabulary: tell it what to look for
                from catalog import CATALOG
                try:
                    model.set_classes([c for c in SUPPORTED if c not in custom] + [PERSON])
                except ImportError as e:  # YOLO-World encodes the prompts with CLIP
                    raise RuntimeError(
                        "YOLO-World needs CLIP: run .venv/bin/pip install -r backend/requirements.txt") from e
                self._label = {c.get("prompt", c["category"]): c["category"] for c in CATALOG}
        except Exception as e:  # noqa: BLE001
            log.exception("model load failed")
            self.status.update(camera="error", error=f"Model load failed: {e}")
            return
        class_ids = [i for i, n in model.names.items() if self._label.get(n, n) in ALIASES or n == PERSON]
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

        warning = None
        if float(frame[::8, ::8].mean()) < 8:  # e.g. Continuity Camera paused or lens covered
            warning = "The camera is sending black frames. Check the lens isn't covered."
        global_motion = self.motion.update(frame)
        self.status["motion"] = round(global_motion, 3)

        if self.modes.reset_tracker:  # new viewpoint: drop ByteTrack identities
            self.modes.reset_tracker = False
            self._reset_tracker(model)
        self.modes.on_frame(global_motion, lambda: self._scan(model, full))

        # Whole-view change outside Reposition mode: hold location updates instead of logging moves.
        # A worn camera moves all the time; there the memory never reports moves (see memory.py).
        monitoring = self.modes.mode == MONITORING
        fixed = self.camera_mode == "fixed"
        self._shift_frames = self._shift_frames + 1 if global_motion > self.camera_shift_motion else 0
        if fixed and monitoring and self._shift_frames >= 3:
            self.memory.suspend(3.0)
            self.status["camera_shift_at"] = time.time()
        if fixed and monitoring and time.time() - self.status.get("camera_shift_at", 0) < 10:
            warning = warning or ("The camera view changed a lot. If you moved the camera, "
                                  "press Scan room to update its areas.")
        self.status["warning"] = warning

        hands = []
        try:
            obs = self._detect(model, frame, class_ids) + self._detect_items(frame)
            for o in obs:
                o.motion = self.motion.local(o.bbox)
            if monitoring:
                if self.presence.update(obs) == "left":
                    log.info("person left the view")
            else:  # camera is being moved: nobody "leaves"
                self.presence.reset()
            self.status.update(self.presence.status())
            events = self.memory.observe(obs, frame_id=self._frame_id)
            for ev in events:
                if fixed:  # worn camera: photos come from the observation events below
                    self.snapshots.submit(ev, self._frame_for(ev.get("frame_id")))
                log.info("%s %s -> %s", ev["event_type"], ev["name"], ev["region"])
            if monitoring:
                hands = self.hands.detect(frame) if self.hands else []
                self._observe_wearable(obs, hands)
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
        if self.hands is not None and self.hands.available:
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
                     "timestamp": ev["timestamp"], "bbox": ev["bbox"],
                     "region": locate((ev["bbox"][0] + ev["bbox"][2]) / 2, (ev["bbox"][1] + ev["bbox"][3]) / 2,
                                      self.regions),
                     "confidence": ev["confidence"], "view_id": ev["view_id"]}
            self.snapshots.submit(photo, self._frame_for(ev["frame_id"]),
                                  on_saved=lambda sid, eid=ev["event_id"]: db.set_observation_snapshot(eid, sid))

    def _scan(self, model, reference: np.ndarray) -> tuple[bytes | None, list[dict]]:
        """Scan room: detect furniture over the last few (steady) frames and propose areas."""
        if self._scan_model is None and self.scan_model_path:
            try:
                from ultralytics import YOLO
                self._scan_model = YOLO(self.scan_model_path)
            except Exception:  # noqa: BLE001
                log.exception("scan model unavailable; using the tracking model")
                self.scan_model_path = None
        model = self._scan_model or model
        ids = [i for i, n in model.names.items() if n in FURNITURE]
        per_frame = []
        for _, f in list(self._ring)[-5:]:
            small = self._resize(f, self.frame_width)
            h, w = small.shape[:2]
            res = model.predict(small, conf=0.25, classes=ids, imgsz=self.frame_width,
                                device=self.device, verbose=False)[0]
            per_frame.append([(model.names[int(c)], float(cf), (b[0] / w, b[1] / h, b[2] / w, b[3] / h))
                              for b, c, cf in zip(res.boxes.xyxy.tolist(), res.boxes.cls.tolist(),
                                                  res.boxes.conf.tolist())])
        proposal = propose_regions(per_frame)
        log.info("scan found %s", [p["name"] for p in proposal])
        return self._encode(reference, 85), proposal

    def _frame_for(self, frame_id: int | None) -> np.ndarray | None:
        for fid, f in reversed(self._ring):
            if fid == frame_id:
                return f
        return None

    @staticmethod
    def _reset_tracker(model) -> None:
        try:
            for t in model.predictor.trackers:
                t.reset()
        except Exception:  # noqa: BLE001
            model.predictor = None  # forces a fresh predictor + tracker on the next call

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
        res = m.predict(frame, conf=0.25, imgsz=640, device=self.device, verbose=False)[0]
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
        for r in list(self.regions):  # region overlays
            p0, p1 = (int(r.x0 * w), int(r.y0 * h)), (int(r.x1 * w) - 1, int(r.y1 * h) - 1)
            cv2.rectangle(out, p0, p1, (235, 235, 235), 1)
            cv2.putText(out, r.name, (p0[0] + 6, p0[1] + 18), cv2.FONT_HERSHEY_SIMPLEX,
                        0.5, (245, 245, 245), 1, cv2.LINE_AA)
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
        if self.modes.mode != MONITORING:
            cv2.rectangle(out, (0, 0), (w, 28), (40, 40, 40), -1)
            cv2.putText(out, "Monitoring paused", (10, 19), cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                        (230, 230, 230), 1, cv2.LINE_AA)
        jpg = self._encode(out)
        if jpg:
            with self._jpeg_lock:
                self._jpeg = jpg
                self._jpeg_id = self._frame_id
        self.status["detections"] = [
            {"category": o.category, "name": display_name(o.category),
             "confidence": round(o.confidence, 2), "track_id": o.track_id} for o in obs]
