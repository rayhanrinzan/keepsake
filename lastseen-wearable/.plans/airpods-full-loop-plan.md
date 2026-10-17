# Last Seen — AirPods Full-Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `lastseen/` package so one AirPods case, seen by an iPhone high in a corner, runs the full loop: enroll by pick-up/put-down → move → ask by voice → spoken zone answer → memory frame shows the circled snapshot + clip.

**Architecture:** One Python process. A capture thread keeps the latest frame. A vision thread runs hands + detector + CLIP identity + change detection and feeds a pure per-item state machine. The state machine is the only writer of SQLite. An in-process bus fans events out to FastAPI (MJPEG, WebSocket, REST), the answer engine (templates + Chalk AI Router), and voice. A `FakeTracker` publishes scripted events so tracks B/C/D build in parallel before the real tracker exists.

**Tech Stack:** Python 3.12 (existing `.venv`), Ultralytics YOLO-World (`models/yolov8s-worldv2.pt`), OpenAI `clip` ViT-B/32 (`models/clip/ViT-B-32.pt`), MediaPipe Tasks HandLandmarker, OpenCV, FastAPI + uvicorn, pydantic v2, shapely, faster-whisper `base.en`, sounddevice, macOS `say`, `openai` client → Chalk AI Router, rapidfuzz, pytest.

**Spec:** `.plans/airpods-full-loop-spec.md` (read it with this plan). Build rules: `CLAUDE.md`.

## Global Constraints

- **Timing:** Task 0 is pre-event (hardware + testing, throwaway script). Product code in `lastseen/` is written only after the event clock starts.
- **Order at the event:** Tasks 1–5 first (one person, ~1–2 h). Then three parallel tracks: **A** = Tasks 6–11 then 11b, **B** = Tasks 12–15, **C/D** = Tasks 16–17. Task 18 is last.
- `python -m lastseen` must start the app after every commit.
- Every feature sits behind a `features.*` flag in `config.yaml`.
- Location and state come only from the store/state machine, never from the LLM. LLM hard timeout is **2.5 s**, then template text.
- No image leaves the laptop. Only text goes to Chalk. Frames are never written to disk except `data/clips/` snapshots/clips, which are deleted after **24 h**.
- No AirPods-specific code. The item exists only in `config.yaml` and `data/gallery/airpods/`.
- **No SQLite schema change.** Use the CLAUDE.md §6 tables exactly. `uncertain` = `events.confidence < engine.uncertain_conf` (**0.6**). Per-item extras go in `data/gallery/<item_id>/meta.json`, `pos_*.npy`, `neg.npy`, `template.png`.
- Every tracked item needs a gallery. Config-only items with no gallery are "not enrolled yet" and never tracked.
- One person handles objects at a time. The target is a base M1/M2 Mac: the vision tick (hands + tracker) aims for **≥ 6/s**, and YOLO-World runs every **3rd** tick.
- Thresholds start at: `sim_thresh 0.70`, `margin_follow 0.02`, `margin_reacquire 0.04`, `reacquire_bonus 0.05`, `held_frames 3`, `placed_frames 6`, `missing_frames 10`, `still_px 5`, `move_px 25`, `near_hand_px 150`, crop pad **15%**, detector `conf 0.001`, `imgsz 1280`, boxes > **25%** of the frame dropped, gallery cap **12**.
- These detector/identity values were measured on 2026-10-16 with the prototype (see spec §8a). Don't raise `conf` back above 0.01: YOLO-World scores the AirPods case at only 0.001–0.02.
- Leaving = **person left the camera's view** only (no doors, door lines, ankles or door warnings). Person tracking: Ultralytics `yolo26n.pt` (class 0) + ByteTrack. A track has left when its last box was within **3%** of a frame edge and it has been missing **1 s**. Four configured demo items: `airpods`, `glasses`, `sleeping_mask`, `playing_cards` (spec §4.12), all `critical: false`.
- Every background loop catches, logs and continues.
- Deviation from CLAUDE.md (log it in `NOTES.md`): no `webrtcvad`. faster-whisper's built-in `vad_filter` (as in the prototype) replaces it.
- Tests use fakes (`FakeEmbedder`, `FakeHands`, `FakeDetector`). The unit test suite must never load CLIP, YOLO, MediaPipe, whisper or call `say`.
- Run tests with `.venv/bin/python -m pytest`.

## Review Focus

1. **The camera drops mid-run** (Continuity Camera pauses when the phone locks). Capture keeps retrying, `/health` shows `camera_fps 0` in red, and the app recovers when frames return. Test in Task 3.
2. **A question about something not tracked** ("where's my wallet?") or a config item never enrolled. The answer says so in plain words (`item_id` null / "I haven't been shown your glasses yet"), with no crash and no guess. Tests in Task 13.
3. **The app restarts mid-session.** Item state, zone, last event and `uncertain` come back from SQLite, and galleries reload from disk, so the answer is unchanged. Tests in Tasks 2 and 7.
4. **Two asks in quick succession, or an ask while speaking.** Answers queue and never overlap, and the listener is muted until `say` exits, so it never transcribes its own voice. Test in Task 15.
5. **The item rests outside every drawn zone.** The answer names the nearest zone ("on the floor near the desk") or "in the room", never `None`. Test in Task 6.

---

## File Structure

```
lastseen/
  __main__.py          # build Config, store, bus, camera, server, vision/fake tracker, voice; run uvicorn
  config.py            # pydantic models + load_config(); device detection
  bus.py               # thread-safe pub/sub + asyncio bridge for /ws
  types.py             # Box, Candidate, TickObs, TrackerEvent dataclasses
  capture/camera.py    # LatestFrameCamera (live + replay)
  capture/ringbuffer.py
  vision/embedder.py   # ClipEmbedder (real) — only file that imports clip
  vision/identity.py   # Gallery (sidecar load/save), Identity scoring
  vision/detector.py   # Detector (YOLO-World wrapper)
  vision/hands.py      # HandDetector (MediaPipe)
  vision/people.py     # PeopleTracker (Ultralytics yolo26n + ByteTrack) + LeaveWatcher
  vision/change.py     # ChangeDetector (background + blobs)
  engine/zones.py      # Zone, ZoneMap
  engine/tracker.py    # ItemTracker pure state machine
  engine/enroll.py     # EnrollSession
  engine/vision_loop.py# VisionLoop thread: wires everything, budget, overlay, metrics
  engine/fake.py       # FakeTracker
  memory/store.py      # Store (SQLite)
  memory/clips.py      # write_snapshot, write_clip, cleanup_old
  brain/intents.py     # parse_question
  brain/answer.py      # build_answer
  brain/llm.py         # ChalkLLM
  voice/speak.py       # Speaker
  voice/listen.py      # Listener
  server/app.py        # create_app()
  server/static/frame.html, dashboard.html, manifest.json
  tools/list_cameras.py, draw_zones.py, reset.py
tests/                 # mirrors package; tests/fakes.py holds shared fakes
spikes/corner_check.py # Task 0 throwaway
config.yaml  zones.json  NOTES.md  THIRD_PARTY_NOTICES.md  requirements.txt  .gitignore
```

---

### Task 0: Corner check (PRE-EVENT, throwaway, no tests)

**Files:** Create `spikes/corner_check.py`, `NOTES.md`

- [ ] **Step 1: Mount the iPhone high in the corner** over the mock room (desk, tray, bed + blanket). Plug it in and turn auto-lock off. Find its index with a 6-line `cv2.VideoCapture(i)` loop.
- [ ] **Step 2: Download the hand model** to `models/hand_landmarker.task` from the MediaPipe hand landmarker model page (verify the URL there).
- [ ] **Step 3: Write `spikes/corner_check.py`** (it may copy prototype code). For 60 s per placement (case on desk, tray, bed), print the YOLO-World hit rate for the prototype's 4 prompts at `imgsz` 960 and 1280, the median case box size in px, and the FPS of YOLO-World, CLIP (6 crops) and HandLandmarker separately. Also report the hand detection rate while you pick the case up 10 times, and for `yolo26n.pt`: its FPS and how often a person is found as you walk around and out of view.
- [ ] **Step 4: Record numbers in `NOTES.md`** under "Corner check", and record the §7 test clips (A1–A5) as mp4s in `eval/clips/` for replay.

---

### Task 1: Repo, config, entry point (Setup)

**Files:** Create `.gitignore`, `requirements.txt`, `config.yaml`, `lastseen/__init__.py`, `lastseen/config.py`, `lastseen/__main__.py`, `lastseen/types.py`, `tests/test_config.py`, `tests/fakes.py`

**Interfaces:**
- Produces: `load_config(path="config.yaml") -> Config`. `Config` fields: `camera(source:int|str=0, width=1280, fps_target=8, replay_video:str|None)`, `items: list[ItemCfg(id, display_name, prompt:str|None, extra_prompts:list[str]=[], synonyms:list[str], critical=False)]`, `detector(conf=0.001, imgsz=1280, every_n=3, max_area_frac=0.25, model="models/yolov8s-worldv2.pt")`, `identity(sim_thresh=0.70, margin_follow=0.02, margin_reacquire=0.04, reacquire_bonus=0.05, crop_pad=0.15, gallery_cap=12)`, `engine(held_frames=3, placed_frames=6, missing_frames=10, still_px=5, move_px=25, near_hand_px=150, uncertain_conf=0.6)`, `persons(model="models/yolo26n.pt", every_n=2, edge_frac=0.03, leave_after_s=1.0)`, `features(voice, memory_frame, chalk_llm, fake_tracker=False, search_sense=False, photon=False)`, `people(user_name, caregiver_name)`, `paths(data="data", models="models")`, and a computed `device: Literal["mps","cuda","cpu"]`.
- Produces `lastseen/types.py`: `Box = tuple[int,int,int,int]`; `@dataclass Candidate(box: Box, sim: float, margin: float, source: Literal["det","tmpl","change","stored"], det_conf: float = 0.0)`; `@dataclass Person(track_id: int, box: Box, feet: tuple[int,int])`; `@dataclass TickObs(ts: float, frame_wh: tuple[int,int], hands: list[Box], candidates: list[Candidate], change_boxes: list[Box], persons: list[Person] = [], left_view: list[int] = [])` (use `field(default_factory=list)`); `@dataclass TrackerEvent(kind: Literal["PICKED_UP","PLACED","SEEN","HIDDEN","CARRIED_OUT"], item_id: str, ts: float, from_zone: str|None, to_zone: str|None, bbox: Box|None, confidence: float)`.

- [ ] **Step 1: `git init`, `.gitignore`** (`data/`, `models/`, `.venv/`, `__pycache__/`, `.env`, `answers/`, `eval/clips/`). Write `requirements.txt` and install: `uv pip install --python .venv/bin/python mediapipe fastapi "uvicorn[standard]" supervision "pydantic>=2" shapely openai rapidfuzz python-dotenv pytest "lap>=0.5.12"` (`lap` is needed by Ultralytics tracking).
- [ ] **Step 2: Write failing tests** in `tests/test_config.py`:
```python
def test_loads_airpods_item(tmp_path):
    cfg = load_config("config.yaml")
    a = next(i for i in cfg.items if i.id == "airpods")
    assert "earbuds" in a.synonyms and a.critical is False
    assert [i.id for i in cfg.items] == ["airpods","glasses","sleeping_mask","playing_cards"]
def test_defaults():
    cfg = load_config("config.yaml")
    assert cfg.detector.every_n == 3 and cfg.engine.uncertain_conf == 0.6
    assert cfg.identity.sim_thresh == 0.70 and cfg.detector.conf == 0.001 and cfg.device in ("mps", "cuda", "cpu")
def test_bad_value_rejected(tmp_path):
    p = tmp_path / "c.yaml"; p.write_text("camera: {fps_target: -1}\nitems: []")
    with pytest.raises(ValidationError): load_config(p)
```
- [ ] **Step 3: Run** `.venv/bin/python -m pytest tests/test_config.py -v`. Expected: FAIL (import error).
- [ ] **Step 4: Implement `config.py`** (pydantic v2; `fps_target` must be > 0). Write `config.yaml` with the four items from spec §4.12, exactly as in its table (id, display name, prompt, extra prompts, synonyms; all `critical: false`). Also add a top-level `generic_prompts: ["cell phone","remote","white box"]`, which the detector always adds. Write `types.py`. Write `__main__.py`, which for now loads config, sets logging (console + `data/logs/session-<ts>.jsonl`), and logs "started".
- [ ] **Step 5: Run tests and `.venv/bin/python -m lastseen`.** Expected: PASS, and the app logs "started".
- [ ] **Step 6: Commit** `feat: package skeleton and config`.

---

### Task 2: Bus + store (Setup)

**Files:** Create `lastseen/bus.py`, `lastseen/memory/store.py`, `lastseen/tools/reset.py`, `tests/test_bus.py`, `tests/test_store.py`

**Interfaces:**
- Produces `Bus`: `publish(type: str, **payload) -> None` (adds `type` and `ts`), `subscribe() -> queue.Queue[dict]`, `unsubscribe(q)`. Thread-safe. Slow subscribers drop their oldest message (maxsize 200).
- Produces `Store(path: str, bus: Bus)`: `upsert_item(id, display_name, critical, state, zone, bbox, confidence, last_seen_ts, last_event_id=None) -> None`; `add_event(ev: TrackerEvent, snapshot_path=None, clip_path=None) -> int`; `get_item(id) -> dict|None`; `list_items() -> list[dict]`; `recent_events(n=20, item_id=None) -> list[dict]`; `last_event(item_id, kinds: tuple[str,...]) -> dict|None`; `add_ask(source, question, item_id, answer, state, zone, latency_ms) -> int`; `recent_asks(n=20) -> list[dict]`; `reset_states() -> None` (clears events/asks, sets items to UNKNOWN). Event and item dicts include `uncertain = confidence < uncertain_conf`. `add_event` publishes `event` and `upsert_item` publishes `item_update`, with the §4.10 shapes (`snapshot_url = "/clips/" + filename`).

- [ ] **Step 1: Write failing tests:**
```python
def test_publish_reaches_subscriber():  # bus
    b = Bus(); q = b.subscribe(); b.publish("event", x=1)
    m = q.get(timeout=1); assert m["type"] == "event" and m["x"] == 1 and "ts" in m
def test_add_event_publishes_and_returns_id(tmp_path):
    s, q = make_store(tmp_path)
    eid = s.add_event(TrackerEvent("PLACED","airpods",1.0,"tray","desk",(1,2,3,4),0.9))
    assert eid == 1 and q.get(timeout=1)["event"]["to_zone"] == "desk"
def test_uncertain_derived_from_confidence(tmp_path):
    s, _ = make_store(tmp_path); s.add_event(TrackerEvent("PLACED","airpods",1.0,None,"desk",(1,2,3,4),0.5))
    assert s.recent_events(1)[0]["uncertain"] is True
def test_state_survives_restart(tmp_path):   # Review Focus 3
    s, _ = make_store(tmp_path); s.upsert_item("airpods","AirPods",False,"PLACED","desk",(1,2,3,4),0.9,5.0)
    s2 = Store(str(tmp_path/"db.sqlite"), Bus()); assert s2.get_item("airpods")["zone"] == "desk"
def test_reset_keeps_items_clears_events(tmp_path): ...  # state UNKNOWN, recent_events == []
```
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.** Use the exact CLAUDE.md §6 DDL. Store takes `uncertain_conf` (default 0.6). Use one `sqlite3` connection with `check_same_thread=False` + `threading.Lock`. `tools/reset.py` calls `reset_states()` and leaves `data/gallery/` alone.
- [ ] **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit** `feat: event bus and sqlite store`.

---

### Task 3: Capture + ring buffer (Setup)

**Files:** Create `lastseen/capture/camera.py`, `lastseen/capture/ringbuffer.py`, `lastseen/tools/list_cameras.py`, `tests/test_capture.py`

**Interfaces:**
- Produces `LatestFrameCamera(source: int|str, width: int, replay: str|None)`: `.start()`, `.stop()`, `get_latest() -> tuple[np.ndarray|None, float, int]` (frame, ts, seq), `.fps -> float` (EMA), `.ok -> bool` (a frame within the last 2 s). Frames are resized to `width`. Replay mode loops the mp4 at its own fps. Port the prototype's `LatestFrame` (keep the newest frame, `CAP_PROP_BUFFERSIZE=1`). On read failure it sleeps, reopens after 2 s, and never raises.
- Produces `RingBuffer(seconds=6.0, width=640)`: `push(frame, ts)`, `window(t0, t1) -> list[tuple[float, np.ndarray]]`.

- [ ] **Step 1: Write failing tests.** A fixture writes a 2 s, 10 fps synthetic mp4 (frame index drawn as text) to `tmp_path`.
```python
def test_replay_resizes_and_advances(video): cam = LatestFrameCamera(0,320,str(video)); cam.start(); time.sleep(0.5)
    f, ts, seq = cam.get_latest(); assert f.shape[1] == 320 and seq > 0
def test_dead_source_does_not_raise():   # Review Focus 1
    cam = LatestFrameCamera("/nonexistent.mp4",320,None); cam.start(); time.sleep(0.5)
    assert cam.get_latest()[0] is None and cam.ok is False and cam.fps == 0
def test_ringbuffer_window_and_eviction(): rb = RingBuffer(1.0, 64); push 20 frames at ts 0..1.9
    assert all(1.0 - 1e-6 <= t for t,_ in rb.window(0, 99)); assert rb.window(1.2,1.5)[0][1].shape[1] == 64
```
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement both classes and `list_cameras.py`** (try indices 0–5, print resolution, save `data/cam_<i>.jpg`).
- [ ] **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit** `feat: latest-frame camera, replay, ring buffer`.

---

### Task 4: Server skeleton (Setup)

**Files:** Create `lastseen/server/app.py`, `tests/test_server.py`. Modify `lastseen/__main__.py`.

**Interfaces:**
- Consumes: `Bus`, `Store`, `LatestFrameCamera`.
- Produces `create_app(ctx: AppContext) -> FastAPI`, where `@dataclass AppContext(cfg, bus, store, camera, metrics: dict, ask_fn: Callable[[str,str], dict] | None, enroll_fn: Callable[..., dict] | None, overlay_fn: Callable[[np.ndarray], np.ndarray] | None)`. Routes: `GET /health` → JSON `{camera_fps, camera_ok, vision_tps, detector_ms, clip_ms, hands_ms, last_event_ts, mic, chalk}`, plus `GET /health.html` for the green/red page. `GET /stream` MJPEG of `overlay_fn(latest)` at ≤ 15 fps. `WS /ws` forwards every bus message. `GET /clips/*` static read-only from `data/clips`. `POST /api/ask` → `ask_fn(question, source)` (503 if None). `POST /api/enroll`, `POST /api/enroll/click` → `enroll_fn`. `GET /frame`, `GET /dashboard` serve static HTML.
- `__main__` builds everything and runs uvicorn on `0.0.0.0:8000`.

- [ ] **Step 1: Write failing tests** with `fastapi.testclient`:
```python
def test_health_reports_camera(ctx): r = client(ctx).get("/health"); assert r.status_code == 200 and "camera_fps" in r.json()
def test_ws_forwards_bus(ctx):
    with client(ctx).websocket_connect("/ws") as ws: ctx.bus.publish("show_answer", answer={"text":"hi"}); assert ws.receive_json()["type"] == "show_answer"
def test_ask_503_without_engine(ctx): assert client(ctx).post("/api/ask", json={"question":"x","source":"dashboard"}).status_code == 503
```
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.** The WS handler runs `bus.subscribe()` in a thread (`asyncio.to_thread(q.get)`) and unsubscribes on disconnect.
- [ ] **Step 4: Run tests, then `python -m lastseen` with `camera.replay_video` set**, and open `http://localhost:8000/stream`. Expected: PASS, and the video plays.
- [ ] **Step 5: Commit** `feat: fastapi server, mjpeg, websocket bus`.

---

### Task 5: Clips + FakeTracker (Setup — unblocks B/C/D)

**Files:** Create `lastseen/memory/clips.py`, `lastseen/engine/fake.py`, `tests/test_clips.py`, `tests/test_fake.py`

**Interfaces:**
- Produces `write_snapshot(frame, bbox: Box, label: str, out_dir: Path) -> Path`, which spotlights + circles the bbox (port the prototype's `render_answer` look: dim outside the circle, yellow ring) and adds the zone label. `write_clip(frames: list[tuple[float,np.ndarray]], out_dir: Path, fps=8) -> Path|None`: tries `avc1`, then `mp4v`, and returns None when there are no frames. `cleanup_old(out_dir, max_age_s=86400) -> int` returns how many files it deleted.
- Produces `FakeTracker(store, bus, camera, clips_dir)`: a thread that, every 20 s, plays `PICKED_UP airpods from=tray` → 3 s → `PLACED to=desk` → 20 s → `PICKED_UP from=desk` → 3 s → `PLACED to=tray`. Each event has a real snapshot from the current camera frame and an `upsert_item`. Enabled when `features.fake_tracker`.

- [ ] **Step 1: Write failing tests:**
```python
def test_snapshot_written(tmp_path): p = write_snapshot(np.zeros((360,640,3),np.uint8),(100,100,140,140),"desk",tmp_path); assert p.exists() and cv2.imread(str(p)) is not None
def test_clip_empty_returns_none(tmp_path): assert write_clip([], tmp_path) is None
def test_cleanup_deletes_old_only(tmp_path): old, new = files; os.utime(old,(0,0)); assert cleanup_old(tmp_path) == 1 and new.exists()
def test_fake_tracker_writes_events(tmp_path): ft.step_once(); assert [e["kind"] for e in store.recent_events(5)][::-1][:2] == ["PICKED_UP","PLACED"]
```
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.** Expose `FakeTracker.step_once()` (runs one pick→place pair with no sleeps) so it can be tested. Start a 1 h cleanup timer in `__main__`.
- [ ] **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit** `feat: snapshots, clips, fake tracker`. **Announce to the team: §4.10 interfaces are live, and the parallel tracks start now.**

---

### Task 6: Zones (Track A)

**Files:** Create `lastseen/engine/zones.py`, `lastseen/tools/draw_zones.py`, `zones.json` (sample), `tests/test_zones.py`

**Interfaces:**
- Produces `@dataclass Zone(name, type: Literal["surface","cover","privacy"], polygon: list[tuple[float,float]])`, with polygon coordinates normalized 0–1 so they are resolution-independent. `ZoneMap.load(path) -> ZoneMap`; `zone_at(box: Box, frame_wh) -> Zone|None` (contains the bbox bottom-center); `nearest(box, frame_wh) -> tuple[Zone, float]`; `describe(box, frame_wh) -> str` returns "on the desk" / "under the blanket on the bed" (cover) / "on the floor near the desk" (none, nearest within 15% of the frame width) / "in the room"; `privacy_mask(frame_wh) -> np.ndarray|None`.
- `draw_zones.py`: OpenCV click tool on a frozen frame from `camera.source`. Click points, press Enter, type a name and type, and save. (This is a one-off tool, so a cv2 window is OK here.)

- [ ] **Step 1: Write failing tests** using a two-zone map (desk = left half surface, bed = right-top cover):
```python
def test_zone_by_bottom_center(): assert zm.zone_at((10,10,50,90),(200,100)).name == "desk"
def test_cover_phrase(): assert zm.describe(box_in_bed, wh) == "under the blanket on the bed"
def test_outside_all_zones_names_nearest():   # Review Focus 5
    assert zm.describe(box_just_below_desk, wh) == "on the floor near the desk"
def test_far_from_everything(): assert zm.describe(box_far, wh) == "in the room"
```
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement with `shapely`.** The cover phrase uses `zone.cover_phrase` from an optional JSON field (default `"under the blanket on the {name}"`).
- [ ] **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit** `feat: zones and zone editor`.

---

### Task 7: Detector, embedder, identity (Track A)

**Files:** Create `lastseen/vision/detector.py`, `lastseen/vision/embedder.py`, `lastseen/vision/identity.py`, `tests/test_identity.py`. Add `FakeEmbedder` to `tests/fakes.py`.

**Interfaces:**
- Produces `Detector(cfg)`: `set_items(items: list[ItemCfg])` maps every prompt (main + extra) to its item_id; `detect(frame) -> list[tuple[str, Box, float]]` drops boxes over `max_area_frac`. Port the prototype's `MODELS` redirect of `ultralytics.nn.text_model.WEIGHTS_DIR`.
- Produces the `Embedder` protocol `embed(frame, boxes: list[Box]) -> np.ndarray (N,512)`, L2-normalized, with crops padded by `crop_pad`. `ClipEmbedder(device, models_dir)` ports the prototype's `Embedder`.
- Produces `Gallery(item_id, root: Path)`: `pos: np.ndarray`, `neg: np.ndarray`, `template: np.ndarray|None`, `meta: dict` (`display_name, prompt, origin: "config"|"enrolled", created_ts`); `save()`, `classmethod load(item_id, root) -> Gallery|None`, `add_pos(emb, cap=12)`.
- Produces `Identity(embedder, cfg.identity)`: `score(frame, gallery, boxes) -> list[tuple[float,float]]` (sim, margin), where sim = max cosine to pos and margin = sim − max cosine to neg. `accepts(sim, margin, reacquire: bool) -> bool` applies `sim ≥ sim_thresh (+reacquire_bonus)` and `margin ≥ margin_follow | margin_reacquire`. `build_negatives(frame, item_box, extra_boxes, n=12) -> np.ndarray` ports the prototype's `_negatives`.
- Produces the module function `template_candidates(frame, template: np.ndarray, k=3) -> list[Box]`, which ports the prototype's multi-scale match (scales 0.35, 0.5, 0.7, 1.0, 1.3; `TM_CCOEFF_NORMED`).

- [ ] **Step 1: Write failing tests.** `FakeEmbedder` maps a crop's mean color to a fixed unit vector, so a "white" crop and a "gray" crop are distinct.
```python
def test_accepts_own_item_rejects_lookalike(): s = ident.score(frame, gal_white, [white_box, gray_box]); assert ident.accepts(*s[0], False) and not ident.accepts(*s[1], False)
def test_template_finds_case(): assert iou(template_candidates(frame_with_case, case_crop_gray)[0], case_box) > 0.5
def test_reacquire_stricter(): assert ident.accepts(0.82, 0.05, False) and not ident.accepts(0.82, 0.05, True)
def test_gallery_roundtrip(tmp_path):   # Review Focus 3
    g = Gallery("airpods", tmp_path); g.pos = v; g.meta = {...,"origin":"enrolled"}; g.save()
    assert np.allclose(Gallery.load("airpods", tmp_path).pos, v)
def test_gallery_cap(): add 20 → len(g.pos) == 12
def test_missing_gallery_is_none(tmp_path): assert Gallery.load("glasses", tmp_path) is None
```
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.** `Detector` and `ClipEmbedder` get no unit tests (they would load models). Instead add `tests/manual/test_models_smoke.py`, marked `@pytest.mark.models` and skipped by default, which runs both on one frame.
- [ ] **Step 4: Run.** Expected: PASS (models test skipped).
- [ ] **Step 5: Commit** `feat: detector, clip embedder, gallery identity`.

---

### Task 8: Hands + change detector (Track A)

**Files:** Create `lastseen/vision/hands.py`, `lastseen/vision/change.py`, `tests/test_change.py`. Add `FakeHands` to `tests/fakes.py`.

**Interfaces:**
- Produces `HandDetector(model_path)`: `detect(frame, ts_ms: int) -> list[Box]`. MediaPipe Tasks HandLandmarker, VIDEO mode, `num_hands=2`. Each box is the landmarks' extent padded 20%. Check the current MediaPipe docs for the Tasks API before writing.
- Produces `ChangeDetector(work_width=640)`: `update(frame, hands: list[Box]) -> None` learns the background only from pixels outside hand boxes, and only after ≥ 1 s with no hands. `snapshot() -> int` freezes a reference and returns its id. `blobs(ref_id: int|None, frame, near: tuple[int,int]|None = None, radius: int|None = None) -> list[Box]` returns changed regions vs the reference (or vs the background if None) in full-frame coordinates. It drops blobs smaller than 0.02% or larger than 5% of the frame, and sorts them by distance to `near`. `drop(ref_id)`. (The method is the builder's choice; frame-diff with blur + threshold + morphology on grayscale is enough.)

- [ ] **Step 1: Write failing tests** on synthetic 320×180 frames (gray background, white 12×10 rectangle = case, skin-colored 40×40 = hand):
```python
def test_appeared_object_found_near_hand():
    cd.update(bg, []); r = cd.snapshot(); f = bg_with_case_at(200,100)
    assert iou(cd.blobs(r, f, near=(205,105), radius=60)[0], case_box) > 0.5
def test_hand_pixels_not_learned(): update with hand present ×30 → blobs(None, bg_without_hand) == []
def test_lighting_noise_ignored(): assert cd.blobs(r, bg + 3) == []
def test_huge_change_ignored(): assert cd.blobs(r, np.full_like(bg, 255)) == []
```
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement both.** `HandDetector` has no unit test; add it to the `models` smoke test.
- [ ] **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit** `feat: hand detector and change detector`.

---

### Task 9: ItemTracker state machine (Track A — the core)

**Files:** Create `lastseen/engine/tracker.py`, `tests/test_tracker.py`

**Interfaces:**
- Consumes: `TickObs`, `Candidate`, `TrackerEvent` (Task 1), `ZoneMap` (Task 6).
- Produces `ItemTracker(item_id, engine_cfg, identity_cfg, zones: ZoneMap)`: fields `state`, `bbox: Box|None` (last *placed* box), `live_box: Box|None` (for overlay: hand box while held), `zone`, `last_placed_ts`, `confidence`. Methods: `restore(item_row: dict)` (from the store after restart), `step(obs: TickObs) -> list[TrackerEvent]`, `needs_global_search() -> bool` (True in UNKNOWN/HIDDEN/CARRIED_OUT), `hand_anchor() -> tuple[int,int]|None` (center of the last holding hand). The tracker does no I/O: candidates arrive already scored (`source="stored"` = verification at the stored bbox).

Rules (spec §4.4), all counts in ticks:
- PLACED: a `stored` candidate failing verification never changes state by itself (occlusion).
- PLACED → HELD needs a hand overlapping `bbox` (IoU > 0.05 or bbox center inside the hand) for `held_frames` **and** then either a failed `stored` verification or an accepted candidate's center ≥ `move_px` from `bbox`. A hand overlapping for `held_frames` with the item still verified at `bbox` counts as a brush: no event. Emits `PICKED_UP(from_zone)`.
- HELD: `live_box` = the overlapping or nearest hand. `bbox`/`zone` are never updated.
- HELD → PLACED: an accepted candidate (any source) whose center is within `near_hand_px` of `hand_anchor()`, with no hand overlapping it, and moving < `still_px` over `placed_frames`. Candidates farther than `near_hand_px` are ignored unless `sim ≥ sim_thresh + 0.10` and `margin ≥ 0.15`. Emits `PLACED(to_zone)`.
- Confidence for PLACED (pinned): `clip(0.4*min(1,(sim-0.70)/0.20) + 0.4*min(1,margin/0.15) + 0.2*change_support, 0, 1)`, where `change_support` = 1 if a `change_boxes` entry has IoU > 0.3 with the candidate.
- Holder: while HELD, `holder_track_id` = the `Person` whose box contains the holding hand (or the nearest person). If `holder_track_id in obs.left_view` while HELD → CARRIED_OUT(to_zone=None) **immediately** (spec §4.11, the main rule).
- HELD with no hands for `missing_frames` and no put-down (fallback): last hand center in a `cover` zone → HIDDEN(to_zone=cover). Within 5% of a frame edge → CARRIED_OUT. Otherwise → UNKNOWN with no event, keeping `bbox`/`last_placed_ts` from the last PLACED.
- PLACED → PLACED moved: an accepted non-`stored` candidate ≥ `move_px` away with no hand, still for `placed_frames` → PLACED with the new zone.
- UNKNOWN/HIDDEN/CARRIED_OUT → PLACED: an accepted candidate (reacquire thresholds already applied by the caller) still for `placed_frames` → PLACED, or SEEN if in the same zone.

- [ ] **Step 1: Write failing tests** with a helper `run(tracker, [obs...])` that collects events, plus builders `hand_at(x,y)` and `cand(box, sim=0.9, margin=0.12, source="det")`:
```python
def test_pickup_then_putdown():  # A2
    evs = run(t_placed_on_tray, pickup_seq() + carry_seq(to=desk_xy) + putdown_seq(desk_box))
    assert [e.kind for e in evs] == ["PICKED_UP","PLACED"] and evs[0].from_zone == "tray" and evs[1].to_zone == "desk"
def test_no_location_while_held():  # A3, problem 4
    run(t, pickup_seq() + [held_obs()]*30); assert t.state == "HELD" and t.zone == "tray"
def test_hand_brush_is_not_pickup(): evs = run(t, [obs(hands=[over_tray], cands=[stored_ok])]*10); assert evs == []
def test_occlusion_keeps_placed():  # A5
    evs = run(t, [obs(cands=[stored_fail])]*40); assert evs == [] and t.state == "PLACED"
def test_far_lookalike_ignored_on_putdown():  # A4
    evs = run(t, pickup_seq() + [obs(cands=[cand(far_box, sim=0.85, margin=0.08)])]*10); assert "PLACED" not in kinds(evs)
def test_weak_putdown_is_uncertain(): ev = putdown with sim=0.81, margin=0.04, no change → ev.confidence < 0.6
def test_held_timeout_in_cover_is_hidden(): assert kinds(run(t, pickup_seq(hand_last_in=bed) + [obs()]*10)) == ["PICKED_UP","HIDDEN"]
def test_held_timeout_nowhere_is_unknown_keeps_last_place(): ... t.state == "UNKNOWN" and t.zone == "tray"
def test_carried_out_when_holder_leaves_view():  # A11
    evs = run(t, pickup_seq(person=7) + [held_obs(person=7, left_view=[7])]); assert kinds(evs) == ["PICKED_UP","CARRIED_OUT"] and evs[-1].to_zone is None
def test_other_person_leaving_ignored(): evs = run(t, pickup_seq(person=7) + [held_obs(person=7, left_view=[9])]*3); assert kinds(evs) == ["PICKED_UP"]
def test_restore_from_row(): t.restore({"state":"PLACED","zone":"desk","bbox":"[1,2,3,4]",...}); assert t.bbox == (1,2,3,4)
```
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement `ItemTracker`** exactly per the rules above. Keep per-state counters, and reset them on every transition.
- [ ] **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit** `feat: hand-led item state machine`.

---

### Task 10: Enrollment session (Track A)

**Files:** Create `lastseen/engine/enroll.py`, `tests/test_enroll.py`

**Interfaces:**
- Consumes: `ChangeDetector`, `Identity`/`Embedder`, `Gallery`, `Detector` output (optional), `Bus`.
- Produces `EnrollSession(item_id, display_name, prompt, change: ChangeDetector, embedder, identity, gallery_root, bus, engine_cfg, timeout_s=20)`: `step(frame, ts, hands: list[Box], det_boxes: list[Box]) -> Literal["waiting_pickup","waiting_putdown","settling","done","failed"]`. On start it calls `change.snapshot()` and publishes `enroll_status`. Stages: a hand appears → `waiting_putdown`. The hand is gone after being present ≥ 0.5 s → look for blobs near the last hand center. Exactly one blob → `settling`. Zero or 2+ blobs → `failed` with the spec's message: "I couldn't tell which thing you put down — try again a bit more in the open". During settling it needs the blob to stay still for `placed_frames`, collects 8 jittered crops (±5% shift), and unions the box with any detector box at IoU > 0.3. It then saves the `Gallery` (pos, neg via `identity.build_negatives`, grayscale template, meta origin=`enrolled`) → `done`. `result() -> tuple[Box, Gallery]|None`.
- Produces `enroll_from_click(frame, item_id, display_name, x, y, ...) -> tuple[Box, Gallery]|None`: the box = the change blob containing (x,y), or else a 60×60 box centered on the click.

- [ ] **Step 1: Write failing tests** with synthetic frames, `FakeEmbedder` and `FakeHands`:
```python
def test_enroll_pickup_putdown_saves_gallery(tmp_path):  # A1
    stages = run_enroll(bg → hand+case → case only ×8); assert stages[-1] == "done"
    g = Gallery.load("airpods", tmp_path); assert len(g.pos) == 8 and g.meta["origin"] == "enrolled" and g.template is not None
def test_two_blobs_fails(tmp_path): assert run_enroll(... two new objects ...)[-1] == "failed"
def test_timeout_fails(tmp_path): no hand for 21 s of ts → "failed"
def test_click_enroll(tmp_path): box, g = enroll_from_click(frame_with_case, "airpods","AirPods", cx, cy, ...); assert iou(box, case_box) > 0.5
```
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit** `feat: pick-up/put-down enrollment`.

---

### Task 11: Vision loop wiring, overlay, budget (Track A)

**Files:** Create `lastseen/engine/vision_loop.py`, `tests/test_vision_loop.py`. Modify `lastseen/__main__.py` (use VisionLoop unless `features.fake_tracker`).

**Interfaces:**
- Consumes everything from Tasks 2–10.
- Produces `VisionLoop(cfg, camera, ring, store, bus, zones, detector, hands, embedder, change, clips_dir)` (a thread): `start()`, `stop()`, `tick(frame, ts) -> None` (one iteration, called by `run()`; public for tests), `start_enroll(item_id, display_name, prompt=None) -> dict`, `click_enroll(item_id, display_name, x, y) -> dict`, `overlay(frame) -> np.ndarray` (supervision annotators: green verified box, amber last-seen, "held" label on the hand, zone outlines, hand boxes), `metrics: dict` (`vision_tps, detector_ms, clip_ms, hands_ms, last_event_ts`).
- Per tick: apply the privacy mask → hands every tick (every 2nd if no hand seen in the last 1 s) → `change.update` → detector every `every_n` ticks (cache the last result) → for each tracker build candidates: `stored` (1 crop at `bbox`) in PLACED; in HELD, det/change/template boxes near `hand_anchor()`; if `needs_global_search()`, det + change + template (template every 6th tick), ≤ 6 crops in one `embed` call → `identity.accepts` (reacquire flag from tracker state) → `tracker.step(obs)`. Each event goes to `store.add_event` with a snapshot (current frame, bbox, `zones.describe`) and a clip (`ring.window(ts-2.5, ts+0.5)`, written 0.5 s later on a timer) for PLACED/HIDDEN/CARRIED_OUT, then `store.upsert_item`. A strong verification every 15th tick adds to the gallery (`sim ≥ thresh+0.08`, `margin > 0.1`). Trackers are created only for items with a gallery and restored from the store on start. Each tick sits in try/except with logging.

- [ ] **Step 1: Write failing integration test** using fakes (`FakeDetector` returns the case box when visible, `FakeHands` scripted, `FakeEmbedder`) on a synthetic sequence: case on tray → hand picks up → hand moves to desk → case on desk.
```python
def test_loop_logs_pickup_and_place(tmp_path):
    for f, ts in seq: loop.tick(f, ts)
    kinds = [e["kind"] for e in store.recent_events(10)][::-1]
    assert kinds == ["PICKED_UP","PLACED"] and store.get_item("airpods")["zone"] == "desk"
    assert Path("data/clips", ...).exists()  # snapshot written
def test_tick_survives_exception(tmp_path): FakeHands raises once → next tick still runs, metrics updated
def test_no_tracker_without_gallery(tmp_path): config has glasses without gallery → no tracker for glasses
```
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.** Wire `ask_fn`/`enroll_fn`/`overlay_fn` into `AppContext` in `__main__`.
- [ ] **Step 4: Run tests, then do a live run against the corner camera** with `features.fake_tracker: false`: enroll the case from the dashboard (or `curl -X POST localhost:8000/api/enroll -d '{"item_id":"airpods","display_name":"AirPods"}'`) and move it. Expected: PASS, and the A1/A2 events appear in `/health` and `/ws`. Check `/health` for `vision_tps ≥ 6` (A6), and if it's lower, tune `every_n`/`imgsz` per `NOTES.md`.
- [ ] **Step 5: Run the recorded A1–A5 clips in replay mode.** Expected: the events match spec §7.
- [ ] **Step 6: Commit** `feat: vision loop wiring, overlay, budget`.

---

### Task 11b: People + leaving the view (Track A, after Task 11)

**Files:** Create `lastseen/vision/people.py`, `tests/test_people.py`. Modify `lastseen/engine/vision_loop.py`.

**Interfaces:**
- Consumes: `Person`, `TickObs` (Task 1), `ItemTracker` (Task 9), `Bus`.
- Produces `PeopleTracker(cfg.persons, device)`: `track(frame) -> tuple[list[Person], sv.Detections]`. It calls `model.track(frame, persist=True, tracker="bytetrack.yaml", classes=[0], verbose=False)`; `Person.feet` = the box bottom-center. Detections come from `sv.Detections.from_ultralytics(result)`.
- Produces `LeaveWatcher(frame_wh, edge_frac=0.03, leave_after_s=1.0, bus=None)`: `update(persons: list[Person], ts: float) -> tuple[list[int], list[int]]` returns (`entered`, `left`). A track is `left` exactly once, when it has been missing ≥ `leave_after_s` and its last box was within `edge_frac` of any frame edge. It is `entered` when a new id first appears. It publishes `person` messages (`entered_view|left_view`). A track missing from the middle of the frame is never `left`; after 10 s it is forgotten silently.
- VisionLoop: run `PeopleTracker` every `persons.every_n` ticks, then `LeaveWatcher.update`, and put `persons` and `left_view` into each `TickObs`.

- [ ] **Step 1: Write failing tests** (no models; `Person`s built by hand, frame 1280×720):
```python
def test_leaving_right_edge_reported_once(): person 7 walks to x2=1275, then absent for 1.5 s → left == [7] exactly once
def test_missing_mid_frame_is_not_leaving(): person 7 centred, absent 3 s → never left
def test_short_gap_at_edge_is_not_leaving(): at edge, absent 0.5 s, reappears → never left
def test_new_id_entered(): first sighting of id 4 → entered == [4]
```
- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/test_people.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement `PeopleTracker`, `LeaveWatcher` and the VisionLoop wiring.** Add the person model to the `models` smoke test.
- [ ] **Step 4: Run tests, then live:** spec A11 and A12. Expected: PASS. `/health` `vision_tps` is still ≥ 6; if not, set `persons.every_n: 3`.
- [ ] **Step 5: Commit** `feat: person tracking and carried-out on leaving view`.

---

### Task 12: Intents (Track B)

**Files:** Create `lastseen/brain/intents.py`, `tests/test_intents.py`

**Interfaces:**
- Produces `@dataclass Intent(kind: Literal["find","held_time","enroll","none"], item_id: str|None, raw_item: str|None)`. `parse_question(text: str, items: list[ItemCfg]) -> Intent`. Regexes: `where('s| is| are| did i put)? (my |the |her |his )?(?P<item>.+)`, `(i )?can'?t find (my |the )?(?P<item>.+)`, `have you seen (my |the |her |his )?(?P<item>.+)`, `when did i last (have|use) (my |the )?(?P<item>.+)`, `enroll (my |the )?(?P<item>.+)`, plus a bare item word followed by "?". The item resolves by exact synonym, then `rapidfuzz.process.extractOne` with score ≥ 80.

- [ ] **Step 1: Write failing tests** for the 5 phrasings in spec A8 (each → `find`, `airpods`), plus:
```python
def test_unknown_item(): i = parse_question("where's my wallet", items); assert i.kind == "find" and i.item_id is None and i.raw_item == "wallet"
def test_chatter_ignored(): assert parse_question("what a nice day", items).kind == "none"
def test_fuzzy(): assert parse_question("where are my air pod", items).item_id == "airpods"
```
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit** `feat: question intents`.

---

### Task 13: Answer engine + /api/ask (Track B)

**Files:** Create `lastseen/brain/answer.py`, `tests/test_answer.py`. Modify `lastseen/__main__.py` (set `ask_fn`).

**Interfaces:**
- Consumes: `Store`, `parse_question`, `ZoneMap.describe`, and `ChalkLLM` (Task 14, optional; None until it lands).
- Produces `AnswerEngine(cfg, store, zones, llm=None, bus=None)`: `ask(question: str, source: str) -> dict` with keys `text, item_id, state, zone, uncertain, snapshot_url, clip_url, ts_placed, latency_ms`. It logs via `store.add_ask` and publishes `show_answer`. `template(item_row, last_event, item_cfg) -> str` uses the CLAUDE.md templates verbatim, with times formatted `%-I:%M`, "I think " prefixed when uncertain, and the zone phrase from `zones.describe` (§4.6). For PLACED: "Your {name} {is|are} {phrase}. You put {it|them} there at {time}." Plurality: names ending in "s" use "are/them". CARRIED_OUT (exact, replaces CLAUDE.md's "out of the room"): "You picked up your {name} at {time} and took {it|them} out of view."
- Copy for the special cases (exact): unknown item → "I'm not tracking anything called {raw_item} yet." Configured but no gallery → "I haven't been shown your {name} yet." Enrolled, no events → "I haven't seen your {name} since you showed it to me."

- [ ] **Step 1: Write failing tests** against a temp store:
```python
def test_placed_answer(): assert eng.ask("where are my airpods","dashboard")["text"] == "Your AirPods are on the desk. You put them there at 3:42."
def test_held(): ... == "You're holding them right now."
def test_uncertain_prefix(): event confidence 0.5 → text.startswith("I think ")
def test_unknown_item_no_crash():   # Review Focus 2
    r = eng.ask("where's my wallet","voice"); assert r["item_id"] is None and "wallet" in r["text"]
def test_not_enrolled(): glasses in config, no gallery → r["text"] == "I haven't been shown your glasses yet."
def test_ask_logged_and_published(): assert store.recent_asks(1)[0]["source"] == "dashboard" and bus msg type == "show_answer"
def test_restart_same_answer(tmp_path):   # Review Focus 3
    a1 = eng.ask(q,"x")["text"]; eng2 = AnswerEngine(cfg, Store(same_db), zones); assert eng2.ask(q,"x")["text"] == a1
```
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.** Wire `ask_fn = engine.ask`.
- [ ] **Step 4: Run tests, then `curl` the 5 phrasings against the FakeTracker app.** Expected: PASS, with correct zones.
- [ ] **Step 5: Commit** `feat: deterministic answer engine and /api/ask`.

---

### Task 14: Chalk AI Router client (Track B)

**Files:** Create `lastseen/brain/llm.py`, `tests/test_llm.py`, `.env.example`

**Interfaces:**
- Produces `ChalkLLM(host, key, env_id, model, timeout_s=2.5)` built from `.env` (`CHALK_API_HOST`, `CHALK_ROUTER_KEY`, `CHALK_ENV_ID`, `CHALK_MODEL`). `parse_item(question, items) -> str|None` makes one tool call, `get_item_status(item_id)`, constrained to config ids. `reword(template_text, facts: dict) -> str` must keep the zone and time words from the template; if not, it returns the template. Both return None or the template on timeout or any error. The client is `openai.OpenAI(base_url=f"https://{host}/v1/router", api_key=key, default_headers={"X-Chalk-Env-Id": env_id}, timeout=2.5)`. **Confirm the host, header and model with Chalk's docs or team at the event; if they differ, the docs win and `NOTES.md` records it.** It sends text only: the question + compact JSON of item states + the last 20 events. No paths, no images.
- `AnswerEngine` uses `llm.parse_item` when the regex gives `none` or `item_id None`, and `llm.reword` when `features.chalk_llm`.

- [ ] **Step 1: Write failing tests** with a stub OpenAI client injected:
```python
def test_timeout_falls_back(): slow stub (3 s) → reword returns template within 2.7 s
def test_reword_dropping_zone_rejected(): stub returns "They're somewhere!" → returns template
def test_payload_has_no_paths(): captured request JSON contains no ".jpg"/".mp4"/"/clips/"
def test_disabled_flag_skips_llm(): features.chalk_llm false → stub never called
```
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement**, and add `chalk` reachability (last call ok/failed) to `metrics` for `/health`.
- [ ] **Step 4: Run tests, then Wi-Fi off + `curl` (A9).** Expected: PASS, with template answers < 1 s.
- [ ] **Step 5: Commit** `feat: chalk ai router with template fallback`.

---

### Task 15: Voice (Track B)

**Files:** Create `lastseen/voice/speak.py`, `lastseen/voice/listen.py`, `tests/test_voice.py`. Modify `__main__` (behind `features.voice`).

**Interfaces:**
- Produces `Speaker(cmd=("say","-v","Samantha","-r","165"), runner=subprocess.Popen)`: `say(text)` enqueues. A worker thread runs one utterance at a time and waits for it to exit. `speaking: threading.Event` is set while running.
- Produces `Listener(on_text: Callable[[str], None], speaking: threading.Event, model="base.en", models_dir)`: port the prototype's `SpeechListener` (pre-warmed `sounddevice` stream, 4.5 s rolling buffer, `vad_filter=True`, RMS silence gate 0.005). It drops audio blocks and clears the buffer while `speaking` is set, plus 0.5 s after. Every transcript goes to `on_text`, then is discarded. `status: str` goes to `/health`. `__main__`: `on_text` → `parse_question` → if `find`, call `engine.ask(text, "voice")` → `speaker.say(answer["text"])`. If `enroll`, call `loop.start_enroll(...)` and say "OK, pick it up and put it down where I can see it."

- [ ] **Step 1: Write failing tests** with a fake runner whose process takes 0.3 s:
```python
def test_utterances_do_not_overlap():   # Review Focus 4
    sp.say("one"); sp.say("two"); wait; assert runner.max_concurrent == 1 and runner.calls == ["one","two"]
def test_speaking_flag_set_during_say(): sp.say("x"); time.sleep(0.05); assert sp.speaking.is_set()
def test_listener_drops_audio_while_speaking(): speaking.set(); lst.feed(block) ×10; assert lst.buffer_len() == 0
```
(`Listener.feed(block)` and `buffer_len()` are the testable seam; the sounddevice callback calls `feed`.)
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run tests, then live: say "where are my AirPods?" from about 2 m away (A7, voice half).** Expected: PASS, and speech starts ≤ 3 s.
- [ ] **Step 5: Commit** `feat: voice in and out with mic mute`.

---

### Task 16: Memory frame page (Track C)

**Files:** Create `lastseen/server/static/frame.html`, `lastseen/server/static/manifest.json`, `tests/test_static.py`

**Interfaces:**
- Consumes: `/ws` messages `show_answer` (§4.10 shape).
- Produces `/frame`: idle shows a big clock + date on a dark background. `show_answer` → full-screen `snapshot_url` image, the item name in very large text, the answer `text`, and `clip_url` in `<video autoplay muted loop playsinline>` (if `clip_url` is null, the snapshot only). It returns to idle after 60 s and reconnects the WS with backoff (1 s → 5 s max). `manifest.json` provides add-to-home-screen. One self-contained HTML file with no external scripts.

- [ ] **Step 1: Write failing test:** `GET /frame` returns 200, and the HTML contains `new WebSocket` and `playsinline`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement the page.**
- [ ] **Step 4: Run test, then manual check:** run with `features.fake_tracker: true`, open `http://<LAN-IP>:8000/frame` on a phone (hotspot), and `curl /api/ask`. The frame shows the snapshot + clip ≤ 2 s. Kill and restart the server: the frame reconnects by itself.
- [ ] **Step 5: Commit** `feat: memory frame page`.

---

### Task 17: Dashboard page (Track D)

**Files:** Create `lastseen/server/static/dashboard.html`. Extend `tests/test_static.py`. Add `GET /api/items` and `GET /api/events?n=50` to `server/app.py` (thin reads over `Store`).

**Interfaces:**
- Consumes: `/stream`, `/ws` (`event`, `item_update`, `enroll_status`, `show_answer`), `/api/items`, `/api/events`, `/api/ask`, `/api/enroll`, `/api/enroll/click`.
- Produces `/dashboard`: the live MJPEG `<img>` (the overlays are drawn server-side by `overlay_fn`); an item list with state chips (PLACED green, HELD blue, HIDDEN amber, CARRIED_OUT gray, UNKNOWN gray); an event timeline with snapshot thumbnails; an ask box; an "Enroll item" form (name → `/api/enroll`) with live `enroll_status` text; and click-on-stream to enroll (sends the click scaled to stream-pixel coordinates to `/api/enroll/click`). One self-contained HTML file.

- [ ] **Step 1: Write failing tests:** `GET /dashboard` returns 200, and `GET /api/items` returns the items from the store.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run test, then manual check against the FakeTracker** (events stream into the timeline, and the ask box answers), then against the real VisionLoop (A1 via the button, and click-enroll).
- [ ] **Step 5: Commit** `feat: dashboard`.

---

### Task 18: Retire prototype, notices, full acceptance (everyone)

**Files:** Move `lastseen_demo.py` and `run_demo.sh` to `legacy/`. Create/modify `THIRD_PARTY_NOTICES.md` and `NOTES.md`.

- [ ] **Step 1: Move the prototype** to `legacy/`, and note in `NOTES.md` which parts were ported where.
- [ ] **Step 2: Write `THIRD_PARTY_NOTICES.md`** with license texts for Ultralytics (AGPL-3.0, so the repo must be public), OpenAI CLIP (MIT), MediaPipe (Apache-2.0), Supervision (MIT) and faster-whisper (MIT).
- [ ] **Step 3: Run the full suite** `.venv/bin/python -m pytest -v`. Expected: all pass (models tests skipped).
- [ ] **Step 4: Run spec §7 A1–A12 live** with the corner iPhone, the mock room and the frame phone on a hotspot. Record pass/fail and real numbers in `NOTES.md` (A1–A12). Enroll all four configured items, and A10: move two of them. Expected: correct events, no code change.
- [ ] **Step 5: Record a backup video** of the full loop.
- [ ] **Step 6: Commit** `chore: retire prototype, notices, acceptance results`.
