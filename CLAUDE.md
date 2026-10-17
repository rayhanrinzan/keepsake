# CLAUDE.md — Keepsake

## Concept
Keepsake (repo: ctrl-f-spatial-memory) is a local spatial-memory assistant for HackHarvard 2026. One camera, pretrained YOLO11n and ByteTrack recognize eight items. When an item settles in a new place, Keepsake saves its location **and a photo**. Users browse a List (default) or a Map, or press Voice ("What are you looking for?") to hear where an item was last seen and see its photo. **Scan room** detects the room's furniture to define areas (user-editable) and lets the camera move without false movement history.

## Architecture
- `backend/catalog.py`: the 12 items (category = YOLO-World text prompt, display name, aliases, icon, per-item `min_conf`). This is the single source of truth.
- `backend/memory.py`: `SpatialMemory.observe(obs, now, frame_id)` runs a per-category state machine (STABLE → POSSIBLE_CHANGE → MOVING → SETTLING → confirm). It returns confirmed events: `first_seen`, `moved`, `moved_within` or `reconfirmed`, with the best frame id and bbox. It also handles pause/resume (with a new view id), suspend (whole-camera shift) and lost-while-moving. `answer_query()` gives grounded, deterministic answers.
- `backend/snapshots.py`: `SnapshotStore.submit(event, frame)` queues a JPEG write on a background thread, with cooldown dedupe, per-item retention, safe filename checks and `clear()`. The capture toggle is stored in the settings table.
- `backend/vision.py`: `VisionWorker` thread. Capture → resize to 1280 (photos and inference, `imgsz=1280` on MPS/CUDA via `pick_device()`; 640 lost small items across a room; preview stream is 640) → `MotionDetector` (frame differencing, global and per bbox) → YOLO-World track (`set_classes(catalog + person)`; needs the `clip` package) → `memory.observe` → `snapshots.submit` with the frame from the ring buffer. It also produces the MJPEG preview, the black-frame and camera-shift warnings, and resets the tracker on reposition.
- `backend/events.py` (stdlib only): wearable observation event contract shared with Photon/voice (`object_observed`, `interaction_candidate`, `possible_pickup`, `placement_confirmed`; `evidence[]` codes; `validate_event`).
- `backend/wearable.py`: `WearableObserver` (issue #4: filtered sightings, no movement claims) and `InteractionDetector` (issue #5: hand–object evidence state machine). Pure Python; tested with synthetic sequences.
- `backend/hands.py`: optional MediaPipe `HandDetector` (Tasks API with `models/hand_landmarker.task`, or legacy `solutions`). Missing means disabled, never an error.
- `backend/furniture.py`: `propose_regions()` clusters per-frame furniture detections from a scan into named areas (Chair 1, Chair 2…).
- `backend/modes.py`: `ModeController` (MONITORING → REPOSITIONING → CALIBRATING → READY_TO_RESUME). Once the view is steady, the worker's `_scan()` runs the scan model (yolo11m) on the last 5 frames and stores the reference JPEG and proposed areas.
- `backend/database.py`: SQLite tables objects, events, snapshots (metadata only) and settings, with an in-place column migration.
- `backend/spatial.py`: `Region` (with furniture `kind`), `locate()` (most specific area → "Near X" → side of room), `place_phrase()`, `validate_regions`, `save_regions`. `regions.json` ships empty.
- `backend/main.py`: FastAPI. `object_view()` builds the canonical object shape that every UI uses. Config comes from `CTRLF_*` env vars. Binds to 127.0.0.1.
- `frontend/src`: React 19, Vite, Tailwind 4 (theme tokens in `index.css`), lucide. `App.tsx` polls health/objects/events every 1.5 s.
  - Components: `ObjectList`, `ObjectDetail` (dialog with photo history), `SnapshotPhoto` (bbox overlay), `RoomMap`, `SearchPanel` (voice conversation state machine plus typed input), `CameraPanel`/`LiveFeed` (polls `/api/camera/frame` ~5 fps instead of MJPEG, which stalled in browsers), `ScanFlow` (with `AreaEditor`), `ActivityFeed`, `PrivacyPanel`.
  - `lib/voice.ts`: `speak()` resolves when speech ends; `listenOnce()` is the hook for a future wake word.

## Run
```bash
cd backend && ../.venv/bin/python main.py          # from Terminal (camera permission is per app)
npm --prefix frontend run dev                       # http://127.0.0.1:5173
cd backend && ../.venv/bin/python check_camera.py 1 # pick/permit a camera index
```
`main.py` refuses to start if port 8000 is already taken (uvicorn starts the camera before binding, so a duplicate would fight over the camera and DB), and uses a 3 s graceful-shutdown timeout because the MJPEG stream never closes. Agent sessions can't get camera permission directly. Launch the backend in Terminal.app, e.g. `open -a Terminal some.command`. To stop it, kill only the listener (`lsof -ti tcp:8000 -sTCP:LISTEN`); killing all users of port 8000 also kills the Vite proxy.

## Test
```bash
.venv/bin/python -m pytest        # 65 tests, synthetic detections; pytest.ini sets pythonpath=backend
npm --prefix frontend run build
```
`tests/conftest.py` has `Clock` (feeds frames at 5 fps) and `obs()` helpers. The API tests point `CTRLF_*` at tmp paths, including a copy of `regions.json`.

## Conventions
- Never fabricate detections, photos or locations in live mode. Synthetic data belongs only in tests.
- Never commit DBs, photos, frames or weights (`backend/data/` and `*.pt` are git-ignored).
  **One exception:** `backend/models/items.pt`, our trained items model, is committed so the team shares it
  (agreed for the hackathon, PR #10). Keep it the only weights file in git; downloadable models
  (YOLO-World, yolo11, `hand_landmarker.task`) stay ignored.
- Re-observing an item from a new camera view is `reconfirmed`, never a movement event.
- Work happens on feature branches. Don't push to main or merge without approval.

## Limitations
- One item per category. Only COCO classes (no keys, wallets or headphones).
- Areas are 2D image rectangles. The Map is drawn in camera view, not top-down. Furniture detection is limited to COCO classes and has false positives, so the user reviews every scan.
- Hand evidence (MediaPipe) is experimental and tuned on synthetic sequences only; `CTRLF_CAMERA_MODE=wearable` (default) turns off movement claims and the camera-shift pause.
- Thresholds were tuned on synthetic tests. Real-camera tuning is still pending (see the README live checklist).
- Polling, not push.

## Next priorities
1. Live tuning of `SETTLE_SECONDS`, `MOVE_THRESHOLD` and the motion threshold with the demo setup.
2. MediaPipe hands for pick-up/put-down evidence (optional; must not weaken the snapshot path).
3. Multi-instance items. Custom classes (keys, wallet).
4. 3D room view from an Apple RoomPlan export (stretch goal, only with real scan data).
