"""The vision thread: camera frame -> hands, change, detector, identity -> per-item trackers -> store.

Everything that touches the ChangeDetector or an EnrollSession runs on this thread (requests from the
server are queued and executed at the next tick). overlay() only reads a snapshot published per tick.
"""
from __future__ import annotations

import logging
import math
import shutil
import threading
import time
from dataclasses import replace
from pathlib import Path

import cv2
import numpy as np

from lastseen.config import Config, ItemCfg
from lastseen.engine.enroll import EnrollSession, enroll_from_click
from lastseen.engine.touch import handle_touch
from lastseen.engine.tracker import ItemTracker
from lastseen.engine.wear_tracker import BestFrame, WearObs, WearStatus, WearTracker, frame_score
from lastseen.memory.clips import write_clip, write_snapshot
from lastseen.types import Box, Candidate, TickObs, TrackerEvent
from lastseen.vision.geometry import iou
from lastseen.vision.identity import Gallery, Identity, template_candidates
from lastseen.vision.people import LeaveWatcher, safe_track

logger = logging.getLogger(__name__)

MAX_BOXES = 6            # non-stored crops per tick (R11.2)
TEMPLATE_EVERY = 6
GALLERY_EVERY = 15
GALLERY_SIM_BONUS = 0.08
GALLERY_MARGIN = 0.10
HAND_IDLE_S = 1.0
CLIP_PRE_S = 2.5
LOG_EVERY_S = 5.0
CLICK_TIMEOUT_S = 10.0
SNAPSHOT_KINDS = ("PLACED", "SEEN", "HIDDEN", "CARRIED_OUT")
GREEN, AMBER, WHITE, CYAN = (80, 220, 80), (0, 176, 255), (255, 255, 255), (220, 200, 0)
GRAY = (150, 150, 150)
STALE_SAME_TICKS = 10    # wearable: identical downscaled frames this many ticks in a row -> camera lost
BEST_MAX_W = 1280        # wearable: best-frame snapshots are downscaled to at most this width
WEAR_NO_ENROLL = {"ok": False, "error": "not available in wearable mode"}
REACQUIRE_PHASES = ("UNTRACKED", "PLACED_GONE", "WITH_YOU")


def _center(b: Box) -> tuple[float, float]:
    return ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)


def _near(b: Box, pt, radius: float) -> bool:
    if pt is None:
        return True
    c = _center(b)
    return math.hypot(c[0] - pt[0], c[1] - pt[1]) <= radius


def _hand_on(box: Box, hands: list[Box]) -> bool:
    c = _center(box)
    return any(iou(h, box) > 0.05 or (h[0] <= c[0] <= h[2] and h[1] <= c[1] <= h[3]) for h in hands)


class VisionLoop(threading.Thread):
    def __init__(self, cfg: Config, camera, ring, store, bus, zones, detector, hands, embedder,
                 change, clips_dir, identity: Identity | None = None, gallery_root=None, people=None,
                 classifier=None, touch=None):
        super().__init__(name="vision", daemon=True)
        self.cfg, self.camera, self.ring, self.store, self.bus = cfg, camera, ring, store, bus
        self.zones, self.detector, self.hands, self.embedder, self.change = zones, detector, hands, embedder, change
        self.clips_dir = Path(clips_dir)
        self.people = people
        self.classifier, self.touch = classifier, touch
        self.touch_item_ids = [i.id for i in cfg.items]   # touch locks only the configured items
        self._watcher: LeaveWatcher | None = None
        self._persons: list = []
        self._left_view: list[int] = []
        self.identity = identity or Identity(embedder, cfg.identity)
        self.gallery_root = Path(gallery_root or Path(cfg.paths.data) / "gallery")
        self.metrics: dict = {"vision_tps": 0.0, "detector_ms": None, "clip_ms": None,
                              "hands_ms": None, "people_ms": None, "last_event_ts": None}
        self.galleries: dict[str, Gallery] = {}
        self.trackers: dict[str, ItemTracker] = {}
        self._refs: dict[str, int] = {}          # item -> change ref taken at PICKED_UP
        self._verified: dict[str, bool] = {}
        self._stored_state: dict[str, str] = {}  # last state written to the store
        self._n = 0
        self._dets: list[tuple[str, Box, float]] = []
        self._hands: list[Box] = []
        self._last_hand_ts = -math.inf
        self._frame: np.ndarray | None = None
        self._ts = 0.0
        self._last_tick_mono: float | None = None
        self._ema_dt: float | None = None
        self._session: EnrollSession | None = None
        self._pending_enroll: tuple | None = None
        self._calls: list[tuple] = []           # (fn, args, done, out) to run on the vision thread
        self._req_lock = threading.Lock()
        self._lock = threading.Lock()            # serializes tick() and inline click_enroll
        self._stop_evt = threading.Event()
        self._log_ts: dict[str, float] = {}
        self._view: dict = {"hands": [], "items": []}
        self._bg_cache: list[Box] | None = None
        self.wear = cfg.camera.mode == "wearable"
        self.best: dict[str, BestFrame] = {}      # wearable: best recent look per item
        self._wear_lock = threading.Lock()
        self._wear_status: list[WearStatus] = []
        self._wear_fresh, self._wear_mono = False, None
        self._fr_hash: bytes | None = None
        self._fr_same = 0
        self.metrics["camera_lost"] = False
        self._init_items()
        if self.wear:
            self._wear_status = self._wear_snapshot()

    # ------------------------------------------------------------------ setup
    def _item(self, item_id: str) -> ItemCfg | None:
        return next((i for i in self.cfg.items if i.id == item_id), None)

    def _load_gallery(self, it: ItemCfg) -> Gallery | None:
        try:
            g = Gallery.load(it.id, self.gallery_root)
        except Exception:
            logger.exception("gallery for %s is unreadable; not tracking it", it.id)
            return None
        return g if g is not None and len(g.pos) else None

    def _init_items(self) -> None:
        for it in self.cfg.items:
            if self.store.get_item(it.id) is None:
                self.store.upsert_item(it.id, it.display_name, it.critical, "UNKNOWN", None, None, None, None)
            if self.wear:
                continue
            g = self._load_gallery(it)
            if g is None:
                continue
            self.galleries[it.id] = g
            self._make_tracker(it.id, self.store.get_item(it.id))
        if self.wear:
            self._init_wear()

    def _make_tracker(self, item_id: str, row: dict) -> ItemTracker:
        t = ItemTracker(item_id, self.cfg.engine, self.cfg.identity, self.zones)
        t.restore(row)
        self.trackers[item_id] = t
        self._stored_state[item_id] = t.state
        return t

    # ------------------------------------------------------------------ thread
    def run(self) -> None:
        period = 1.0 / self.cfg.camera.fps_target
        last_seq = None
        while not self._stop_evt.is_set():
            frame, ts, seq = self.camera.get_latest()
            if frame is None or seq == last_seq:
                self._stop_evt.wait(0.01)
                continue
            last_seq = seq
            t0 = time.monotonic()
            self.tick(frame, ts)
            rest = period - (time.monotonic() - t0)
            if rest > 0:
                self._stop_evt.wait(rest)

    def stop(self) -> None:
        self._stop_evt.set()
        if self.ident is not None:
            self.join(timeout=5)
        if self._session is not None:
            self._session.close()

    # ------------------------------------------------------------------ requests from other threads
    def frame_wh(self) -> tuple[int, int] | None:
        f = self._frame
        return (int(f.shape[1]), int(f.shape[0])) if f is not None else None

    def start_enroll(self, item_id: str, display_name: str, prompt: str | None = None) -> dict:
        if self.wear:
            return dict(WEAR_NO_ENROLL)
        with self._req_lock:
            self._pending_enroll = (item_id, display_name, prompt)
        return {"ok": True, "item_id": item_id}

    def click_enroll(self, item_id: str, display_name: str, x: int, y: int) -> dict:
        if self.wear:
            return dict(WEAR_NO_ENROLL)
        return self._on_thread(self._do_click, item_id, display_name, int(x), int(y))

    def forget(self, item_id: str) -> dict:
        return self._on_thread(self._do_forget, item_id)

    def _on_thread(self, fn, *args) -> dict:
        if not self.is_alive():  # no vision thread (tests, startup): run inline, serialized with tick
            with self._lock:
                return fn(*args)
        req = (fn, args, threading.Event(), {})
        with self._req_lock:
            self._calls.append(req)
        if not req[2].wait(CLICK_TIMEOUT_S):
            return {"ok": False, "error": "timeout"}
        return req[3].get("result", {"ok": False})

    # ------------------------------------------------------------------ tick
    def tick(self, frame: np.ndarray, ts: float) -> None:
        try:
            with self._lock:
                self._tick(frame, ts)
        except Exception as e:
            self._log_exc(f"{type(e).__name__}: {e}")
        finally:
            now = time.monotonic()
            if self._last_tick_mono is not None and now > self._last_tick_mono:
                # EMA of the tick interval (not the rate): one tiny startup gap can't inflate tps for long
                dt = now - self._last_tick_mono
                self._ema_dt = dt if self._ema_dt is None else 0.8 * self._ema_dt + 0.2 * dt
                self.metrics["vision_tps"] = 1.0 / self._ema_dt
            self._last_tick_mono = now
            self._n += 1

    def _log_exc(self, key: str) -> None:
        now = time.monotonic()
        if now - self._log_ts.get(key, -math.inf) >= LOG_EVERY_S:
            self._log_ts[key] = now
            logger.exception("vision tick failed")

    def _tick(self, frame: np.ndarray, ts: float) -> None:
        if self.wear:
            return self._tick_wear(frame, ts)
        frame = self._prepare(frame)
        self._frame, self._ts = frame, ts
        self.ring.push(frame, ts)
        hands = self._run_hands(frame, ts)
        self.change.update(frame, hands, ts)
        det_tick = self._run_detector(frame)
        self._run_people(frame, ts)
        self._serve_requests(frame, ts)
        self._step_enroll(frame, ts, hands)
        self._step_touch(frame, ts, hands)
        self._step_trackers(frame, ts, hands, det_tick)
        self._publish_view()

    def _prepare(self, frame: np.ndarray) -> np.ndarray:
        h, w = frame.shape[:2]
        mask = self.zones.privacy_mask((w, h))
        if mask is None:
            return frame
        out = frame.copy()
        out[mask > 0] = 0
        return out

    def _run_hands(self, frame, ts) -> list[Box]:
        if ts - self._last_hand_ts > HAND_IDLE_S and self._n % 2:
            self._hands = []
            return []
        t0 = time.perf_counter()
        self._hands = []  # stays empty if detect raises
        self._hands = list(self.hands.detect(frame, int(ts * 1000)))
        self.metrics["hands_ms"] = (time.perf_counter() - t0) * 1000
        if self._hands:
            self._last_hand_ts = ts
        return self._hands

    def _run_detector(self, frame) -> bool:
        every_n = 1 if self.wear else self.cfg.detector.every_n   # wearable: seen-again needs every tick
        if self._n % max(1, every_n):
            return False
        t0 = time.perf_counter()
        self._dets = list(self.detector.detect(frame))
        self.metrics["detector_ms"] = (time.perf_counter() - t0) * 1000
        return True

    def _run_people(self, frame, ts) -> None:
        self._left_view = []          # left_view is only handed to the trackers on the tick it was produced
        if self.people is None or self._n % max(1, self.cfg.persons.every_n):
            return
        t0 = time.perf_counter()
        persons, _ = safe_track(self.people, frame)
        self.metrics["people_ms"] = (time.perf_counter() - t0) * 1000
        self._persons = persons
        try:
            wh = (frame.shape[1], frame.shape[0])
            if self._watcher is None or (self._watcher.w, self._watcher.h) != wh:
                p = self.cfg.persons
                self._watcher = LeaveWatcher(wh, p.edge_frac, p.leave_after_s, self.bus)
            _, self._left_view = self._watcher.update(persons, ts)
        except Exception:
            self._left_view = []
            self._log_exc("leave watcher")

    # ------------------------------------------------------------------ enrollment
    def _serve_requests(self, frame, ts) -> None:
        with self._req_lock:
            pending, self._pending_enroll = self._pending_enroll, None
            calls, self._calls = self._calls, []
        if pending is not None and not self.wear:
            if self._session is not None:
                self._session.close()
            self._session = None
            item_id, name, prompt = pending
            if not name and self._item(item_id) is not None:
                name = self._item(item_id).display_name
            debug_dir = self.clips_dir if self.cfg.debug.enroll_diagnostics else None
            try:
                self._session = EnrollSession(item_id, name, prompt, self.change, self.embedder,
                                              self.identity, self.gallery_root, self.bus, self.cfg.engine,
                                              debug_dir=debug_dir)
            except Exception:
                logger.exception("could not start enrollment for %s", item_id)
        for fn, args, done, out in calls:
            try:
                out["result"] = fn(*args)
            except Exception:
                logger.exception("%s failed", fn.__name__)
                out["result"] = {"ok": False}
            finally:
                done.set()

    def _do_click(self, item_id, display_name, x, y) -> dict:
        if self._frame is None:
            return {"ok": False}
        if self._session is not None and self._session.item_id == item_id:
            self._session.close()
            self._session = None
        res = enroll_from_click(self._frame, item_id, display_name, x, y, change=self.change,
                                embedder=self.embedder, identity=self.identity, gallery_root=self.gallery_root,
                                det_boxes=[b for _, b, _ in self._dets], ts=self._ts)
        if res is None:
            return {"ok": False}
        self._finish_enroll(item_id, display_name, None, *res)
        return {"ok": True, "item_id": item_id}

    def _step_enroll(self, frame, ts, hands) -> None:
        s = self._session
        if s is None:
            return
        try:
            stage = s.step(frame, ts, hands, [b for _, b, _ in self._dets])
        except Exception:
            logger.exception("enrollment step failed")
            s.close()
            stage = "failed"
        if stage == "done" and s.result() is not None:
            self._finish_enroll(s.item_id, s.display_name, s.prompt, *s.result())
        if stage in ("done", "failed"):
            self._session = None

    def _step_touch(self, frame, ts, hands) -> None:
        if self.touch is None or self.classifier is None:
            return
        try:
            if self.cfg.features.touch_to_track:
                handle_touch(self, frame, ts, hands)
            else:
                self.touch.update(frame, ts, hands, enabled=False)   # releases any open episodes
        except Exception:
            self._log_exc("touch")

    def _do_forget(self, item_id: str) -> dict:
        if not item_id or "/" in item_id or "\\" in item_id or ".." in item_id:
            return {"ok": False}
        if item_id not in self.trackers and self._item(item_id) is None:
            return {"ok": False}
        if self._session is not None and self._session.item_id == item_id:
            self._session.close()
            self._session = None
        self._drop_ref(item_id)
        self.trackers.pop(item_id, None)
        g = self.galleries.pop(item_id, None)
        self._verified.pop(item_id, None)
        self._stored_state.pop(item_id, None)
        d = self.gallery_root / item_id
        if d.is_dir() and d.resolve().parent == self.gallery_root.resolve():
            shutil.rmtree(d)
        it, row = self._item(item_id), self.store.get_item(item_id) or {}
        name = it.display_name if it else (row.get("display_name") or
                                           (g.meta.get("display_name") if g else None) or item_id)
        self.store.upsert_item(item_id, name, bool(it and it.critical), "UNKNOWN", None, None, None, None)
        logger.info("forgot %s", item_id)
        return {"ok": True}

    def _finish_enroll(self, item_id, display_name, prompt, box: Box, gallery: Gallery) -> None:
        it = self._item(item_id)
        if it is None:
            self.cfg.items.append(ItemCfg(id=item_id, display_name=display_name, prompt=prompt or display_name))
            try:
                self.detector.set_items(self.cfg.items)
            except Exception:
                logger.exception("detector.set_items failed after enrolling %s", item_id)
        elif display_name:
            it.display_name = display_name
        self._lock_item(item_id, box, gallery)

    def _lock_item(self, item_id, box: Box, gallery: Gallery, state: str = "PLACED", confidence: float = 0.9,
                   frame=None, anchor=None) -> None:
        """Start tracking item_id at box: PLACED there, HELD at anchor (lifted from box), or CARRIED_OUT."""
        self._drop_ref(item_id)
        old = self.trackers.get(item_id)
        prev_zone = old.zone if old is not None else (self.store.get_item(item_id) or {}).get("zone")
        wh = (self._frame.shape[1], self._frame.shape[0])
        z = self.zones.zone_at(box, wh)
        zone = z.name if z is not None else None
        self.galleries[item_id] = gallery
        t = self._make_tracker(item_id, {"state": "PLACED", "zone": zone, "bbox": list(box),
                                         "confidence": confidence, "last_seen_ts": self._ts})
        self._verified[item_id] = state == "PLACED"
        if state == "PLACED":
            ev = TrackerEvent("PLACED", item_id, self._ts, prev_zone, zone, box, confidence)
        elif state == "HELD":
            t.start_held(anchor, self._ts)
            ev = TrackerEvent("PICKED_UP", item_id, self._ts, zone, None, box, confidence)
            self._take_ref(item_id)
        else:
            t.restore({"state": "CARRIED_OUT", "zone": None, "bbox": list(box), "confidence": confidence,
                       "last_seen_ts": self._ts})
            ev = TrackerEvent("CARRIED_OUT", item_id, self._ts, zone, None, box, confidence)
        self._emit(ev, wh, frame=frame)

    # ------------------------------------------------------------------ trackers
    def _active(self) -> list[tuple[str, ItemTracker]]:
        paused = self._session.item_id if self._session is not None else None
        return [(i, t) for i, t in self.trackers.items() if i != paused]

    def _bg_blobs(self, frame) -> list[Box]:
        if self._bg_cache is None:
            self._bg_cache = self.change.blobs(None, frame)
        return self._bg_cache

    def _requests(self, frame, hands, det_tick):
        """Per tracker: change_boxes and [(box, source, det_conf, priority)] (R11.3)."""
        radius = 2 * self.cfg.engine.near_hand_px
        tmpl_tick = self._n % TEMPLATE_EVERY == 0
        out = {}
        for item_id, t in self._active():
            dets = [(b, c) for i, b, c in self._dets if i in (item_id, "*")]
            reqs, change_boxes = [], []
            g = self.galleries[item_id]
            if t.state == "PLACED" and t.bbox is not None:
                reqs.append((t.bbox, "stored", 0.0, None))
                bc = _center(t.bbox)
                change_boxes = [b for b in self._bg_blobs(frame) if _near(b, bc, radius)]
                if det_tick or _hand_on(t.bbox, hands):
                    reqs += [(b, "det", c, (1, -c)) for b, c in dets if _near(b, bc, radius)]
                    reqs += [(b, "change", 0.0, (1, 0)) for b in change_boxes]
            elif t.state == "HELD":
                a = t.hand_anchor()
                dist = lambda b: math.hypot(*np.subtract(_center(b), a)) if a is not None else 0.0  # noqa: E731
                ref = self._refs.get(item_id)
                change_boxes = (self.change.blobs(ref, frame, near=a, radius=radius) if ref is not None
                                else [b for b in self._bg_blobs(frame) if _near(b, a, radius)])
                boxes = [(b, "det", c) for b, c in dets] + [(b, "change", 0.0) for b in change_boxes]
                if tmpl_tick:
                    boxes += [(b, "tmpl", 0.0) for b in template_candidates(frame, g.template)]
                reqs += [(b, s, c, (0, dist(b))) for b, s, c in boxes if _near(b, a, radius)]
            elif t.needs_global_search():
                change_boxes = self._bg_blobs(frame)
                reqs += [(b, "det", c, (2, -c)) for b, c in dets]
                reqs += [(b, "change", 0.0, (2, 0)) for b in change_boxes]
                if tmpl_tick:
                    reqs += [(b, "tmpl", 0.0, (2, 0)) for b in template_candidates(frame, g.template)]
            out[item_id] = (reqs, change_boxes)
        return out

    @staticmethod
    def _select(requests) -> tuple[list[Box], dict[str, list[tuple[int, str, float]]]]:
        """Dedupe boxes across trackers; all stored boxes + at most MAX_BOXES others by priority."""
        boxes: list[Box] = []
        index: dict[Box, int] = {}
        per: dict[str, list] = {i: [] for i in requests}

        def take(item_id, box, src, conf):
            box = tuple(int(v) for v in box)
            if box not in index:
                index[box] = len(boxes)
                boxes.append(box)
            if all(k != index[box] for k, _, _ in per[item_id]):
                per[item_id].append((index[box], src, conf))

        for item_id, (reqs, _) in requests.items():
            for b, src, conf, _ in reqs:
                if src == "stored":
                    take(item_id, b, src, conf)
        rest = sorted(((pr, item_id, b, src, conf) for item_id, (reqs, _) in requests.items()
                       for b, src, conf, pr in reqs if src != "stored"), key=lambda r: r[0])
        extra = 0
        for _, item_id, b, src, conf in rest:
            key = tuple(int(v) for v in b)
            if key not in index:
                if extra >= MAX_BOXES:
                    continue
                extra += 1
            take(item_id, key, src, conf)
        return boxes, per

    def _step_trackers(self, frame, ts, hands, det_tick) -> None:
        self._bg_cache = None
        wh = (frame.shape[1], frame.shape[0])
        requests = self._requests(frame, hands, det_tick)
        boxes, per = self._select(requests)
        emb = np.zeros((0, 512), np.float32)
        if boxes:
            t0 = time.perf_counter()
            emb = self.embedder.embed(frame, boxes)
            self.metrics["clip_ms"] = (time.perf_counter() - t0) * 1000
        for item_id, picks in per.items():
            try:
                self._step_one(item_id, picks, boxes, emb, requests[item_id][1], frame, ts, hands, wh)
            except Exception:
                self._log_exc(f"tracker {item_id}")

    def _step_one(self, item_id, picks, boxes, emb, change_boxes, frame, ts, hands, wh) -> None:
        t = self.trackers[item_id]
        rows = [k for k, _, _ in picks]
        scores = self.identity.score_embeddings(emb[rows], self.galleries[item_id]) if rows else []
        cands = [Candidate(boxes[k], s, m, src, conf) for (k, src, conf), (s, m) in zip(picks, scores)]
        stored = next(((c, k) for c, (k, _, _) in zip(cands, picks) if c.source == "stored"), None)
        if stored is not None:
            self._verified[item_id] = self.identity.accepts(stored[0].sim, stored[0].margin, False)
            self._maybe_learn(item_id, t, stored, emb, hands)
        obs = TickObs(ts=ts, frame_wh=wh, hands=list(hands), candidates=cands,
                      change_boxes=change_boxes, persons=list(self._persons),
                      left_view=list(self._left_view))
        for ev in t.step(obs):
            if ev.kind == "PICKED_UP":
                self._take_ref(item_id)
            self._emit(ev, wh)
        if t.state != "HELD":
            self._drop_ref(item_id)
        if t.state != self._stored_state.get(item_id):  # e.g. HELD timeout -> UNKNOWN, no event
            self._upsert(item_id, self.store.get_item(item_id) or {})

    def _maybe_learn(self, item_id, t: ItemTracker, stored, emb, hands) -> None:
        c, k = stored
        g, icfg = self.galleries[item_id], self.cfg.identity
        if (self._n % GALLERY_EVERY or len(g.pos) >= icfg.gallery_cap or _hand_on(c.box, hands)
                or c.sim < icfg.sim_thresh + GALLERY_SIM_BONUS or c.margin <= GALLERY_MARGIN):
            return
        try:
            g.add_pos(emb[k], icfg.gallery_cap)
            g.save()
        except Exception:
            logger.exception("gallery update failed for %s", item_id)

    def _take_ref(self, item_id) -> None:
        self._drop_ref(item_id)
        try:
            self._refs[item_id] = self.change.snapshot()
        except Exception:
            logger.exception("change snapshot failed for %s", item_id)

    def _drop_ref(self, item_id) -> None:
        ref = self._refs.pop(item_id, None)
        if ref is not None:
            self.change.drop(ref)

    # ------------------------------------------------------------------ events -> store
    def _emit(self, ev: TrackerEvent, wh, frame=None) -> None:
        snap = clip = None
        if ev.kind in SNAPSHOT_KINDS:
            t = self.trackers.get(ev.item_id)
            box = ev.bbox or (t.bbox if t is not None else None)
            if ev.kind == "CARRIED_OUT":
                label = "out of view"
            elif self.wear:
                label = "last seen" if ev.kind == "SEEN" else ""
            else:
                label = self.zones.describe(box, wh) if box else ""
            try:
                if box is not None:
                    snap = write_snapshot(self._frame if frame is None else frame, box, label, self.clips_dir)
                if self.cfg.features.clips:
                    clip = write_clip(self.ring.window(ev.ts - CLIP_PRE_S, ev.ts), self.clips_dir,
                                      fps=max(1, round(self.cfg.camera.fps_target)))
            except Exception:
                logger.exception("snapshot/clip failed for %s", ev.item_id)
        eid = None
        try:
            eid = self.store.add_event(ev, snapshot_path=str(snap) if snap else None,
                                       clip_path=str(clip) if clip else None)
            self.metrics["last_event_ts"] = ev.ts
        except Exception:
            logger.exception("store.add_event failed for %s", ev.item_id)
        self._upsert(ev.item_id, {"last_event_id": eid})

    def _upsert(self, item_id, row: dict) -> None:
        t, it = self.trackers[item_id], self._item(item_id)
        name = it.display_name if it else self.galleries[item_id].meta.get("display_name", item_id)
        try:
            self.store.upsert_item(item_id, name, bool(it and it.critical), t.state, t.zone, t.bbox,
                                   t.confidence, t.last_placed_ts, row.get("last_event_id"))
            self._stored_state[item_id] = t.state
        except Exception:
            logger.exception("store.upsert_item failed for %s", item_id)

    # ------------------------------------------------------------------ wearable
    def _init_wear(self) -> None:
        for it in self.cfg.items:
            g = self._load_gallery(it) if it.enabled else None
            if g is None:
                if it.enabled:
                    logger.warning("%s enabled but has no gallery; not tracking it", it.id)
                # an old-session row (e.g. PLACED from fixed mode) must not read as a fact here
                self.store.upsert_item(it.id, it.display_name, it.critical, "UNKNOWN", None, None, None, None)
                continue
            self.galleries[it.id] = g
            self.trackers[it.id] = WearTracker(it.id, self.cfg.engine, self.cfg.wearable)
            self.best[it.id] = BestFrame(self.cfg.wearable.best_frame_window_s)
            self._stored_state[it.id] = "UNKNOWN"
            self.store.upsert_item(it.id, it.display_name, it.critical, "UNKNOWN", None, None, None, None)

    def _wear_snapshot(self) -> list[WearStatus]:
        out = []
        for item_id, t in self.trackers.items():
            it = self._item(item_id)
            out.append(WearStatus(item_id, it.display_name if it else item_id, t.phase, t.unseen_s,
                                  t.last_seen_ts, t.sightings))
        return out

    def wear_status(self) -> tuple[list[WearStatus], bool]:
        """Last published statuses (copies) and whether the camera is delivering fresh, recent ticks."""
        with self._wear_lock:
            status, fresh, mono = [replace(s) for s in self._wear_status], self._wear_fresh, self._wear_mono
        return status, bool(fresh and mono is not None
                            and time.monotonic() - mono < self.cfg.wearable.stale_frame_s)

    def _tick_wear(self, frame: np.ndarray, ts: float) -> None:
        frame = self._prepare(frame)
        self._frame, self._ts = frame, ts
        self.ring.push(frame, ts)
        hands = self._run_hands(frame, ts)
        det_tick = self._run_detector(frame)
        fresh = self._freshness(frame)
        self._serve_requests(frame, ts)
        self._step_wear(frame, ts, hands, det_tick, fresh)
        self._publish_view()

    def _freshness(self, frame) -> bool:
        """False once the downscaled frame is identical on STALE_SAME_TICKS consecutive ticks."""
        fresh = True
        try:
            small = cv2.cvtColor(cv2.resize(frame, (32, 18), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
            h = small.tobytes()
            self._fr_same = self._fr_same + 1 if h == self._fr_hash else 1
            self._fr_hash = h
            fresh = self._fr_same < STALE_SAME_TICKS
        except Exception:
            self._log_exc("freshness")
        self.metrics["camera_lost"] = not fresh
        return fresh

    def _step_wear(self, frame, ts, hands, det_tick, fresh) -> None:
        wh = (frame.shape[1], frame.shape[0])
        boxes: list[Box] = []
        confs: list[float] = []
        emb = np.zeros((0, 512), np.float32)
        if det_tick:
            ids = {i.id for i in self.cfg.enabled_items()} | {"*"}
            dets = sorted((d for d in self._dets if d[0] in ids), key=lambda d: -d[2])[:MAX_BOXES]
            boxes = [tuple(int(v) for v in b) for _, b, _ in dets]
            confs = [c for _, _, c in dets]
            if boxes:
                t0 = time.perf_counter()
                emb = self.embedder.embed(frame, boxes)
                self.metrics["clip_ms"] = (time.perf_counter() - t0) * 1000
        for item_id, t in self.trackers.items():
            try:
                cand, accepted = None, False
                if boxes:
                    scores = self.identity.score_embeddings(emb, self.galleries[item_id])
                    k = max(range(len(scores)), key=lambda j: scores[j][0])
                    cand = Candidate(boxes[k], scores[k][0], scores[k][1], "det", confs[k])
                    accepted = self.identity.accepts(cand.sim, cand.margin, t.phase in REACQUIRE_PHASES)
                events = t.step(WearObs(ts, det_tick, fresh, list(hands), cand, accepted, wh))
                for ev in events:
                    if ev.kind in ("PICKED_UP", "PLACED"):
                        self.best[item_id].clear()      # a look from before this move shows the old place
                    self._emit_wear(ev, ts, wh)
                if accepted and t.phase == "PLACED_VISIBLE" and not _hand_on(cand.box, hands):
                    self._offer_best(item_id, ts, frame, cand, wh)
                if t.state != self._stored_state.get(item_id):
                    self._upsert(item_id, self.store.get_item(item_id) or {})
            except Exception:
                self._log_exc(f"tracker {item_id}")

    def _offer_best(self, item_id, ts, frame, cand: Candidate, wh) -> None:
        x1, y1, x2, y2 = (max(0, v) for v in cand.box)
        gray = cv2.cvtColor(frame[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY) if x2 > x1 and y2 > y1 else None
        sharp = float(cv2.Laplacian(gray, cv2.CV_64F).var()) if gray is not None else 0.0
        k = min(1.0, BEST_MAX_W / frame.shape[1])
        small = frame.copy() if k >= 1.0 else cv2.resize(frame, None, fx=k, fy=k, interpolation=cv2.INTER_AREA)
        self.best[item_id].offer(ts, frame_score(cand.sim, sharp, cand.box, wh), small,
                                 tuple(int(v * k) for v in cand.box))

    def _emit_wear(self, ev: TrackerEvent, ts, wh) -> None:
        if ev.kind != "SEEN":
            return self._emit(ev, wh)
        t = self.trackers.get(ev.item_id)
        anchor = t.last_seen_ts if t is not None and t.last_seen_ts is not None else ts
        best = self.best[ev.item_id].best(anchor)   # the best look of the seconds before the last sighting
        if best is None:
            self._emit(ev, wh)
        else:
            frame, box, _ = best
            self._emit(replace(ev, bbox=box), wh, frame=frame)
        self.best[ev.item_id].clear()

    # ------------------------------------------------------------------ overlay
    def _publish_view(self) -> None:
        if self.wear:
            with self._wear_lock:
                self._wear_status = self._wear_snapshot()
                self._wear_fresh, self._wear_mono = not self.metrics["camera_lost"], time.monotonic()
        items = []
        for item_id, t in self.trackers.items():
            it = self._item(item_id)
            items.append((it.display_name if it else item_id, t.state, t.bbox, t.live_box,
                          self._verified.get(item_id, False)))
        self._view = {"hands": list(self._hands), "items": items,
                      "persons": [(p.track_id, p.box) for p in self._persons]}

    def overlay(self, frame: np.ndarray) -> np.ndarray:
        h, w = frame.shape[:2]
        mask = self.zones.privacy_mask((w, h))
        img = frame.copy()
        if mask is not None:
            img[mask > 0] = 0
        view = self._view
        for z in ([] if self.wear else self.zones.zones):
            if z.type == "privacy":
                continue
            pts = np.array([[x * w, y * h] for x, y in z.polygon], np.int32)
            cv2.polylines(img, [pts], True, CYAN, 1, cv2.LINE_AA)
            cv2.putText(img, z.name, tuple(pts[0] + [4, 18]), cv2.FONT_HERSHEY_SIMPLEX, 0.55, CYAN, 1, cv2.LINE_AA)
        for tid, pb in view.get("persons", []):
            cv2.rectangle(img, pb[:2], pb[2:], GRAY, 1)
            cv2.putText(img, f"person {tid}", (pb[0], max(14, pb[1] - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                        GRAY, 1, cv2.LINE_AA)
        for hb in view["hands"]:
            cv2.rectangle(img, hb[:2], hb[2:], WHITE, 1)
        for name, state, bbox, live, verified in view["items"]:
            if self.wear:   # a moving camera: only the live box means anything
                if live is not None:
                    self._box(img, live, name, GREEN)
            elif state == "HELD" and live is not None:
                self._box(img, live, f"{name} (held)", WHITE)
            elif state == "PLACED" and bbox is not None:
                self._box(img, bbox, name if verified else f"{name} (last seen)", GREEN if verified else AMBER)
            elif state in ("UNKNOWN", "HIDDEN") and bbox is not None:
                self._box(img, bbox, f"{name} (last seen)", AMBER)
        return img

    @staticmethod
    def _box(img, b: Box, label: str, color) -> None:
        x1, y1, x2, y2 = (int(v) for v in b)
        cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)
        cv2.putText(img, label, (x1, max(14, y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(img, label, (x1, max(14, y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 1, cv2.LINE_AA)
