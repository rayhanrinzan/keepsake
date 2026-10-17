# Keepsake

> *Your room remembers, so you don't have to.*

Keepsake watches a room through one camera, recognizes eight everyday items, and remembers **where each was last seen, with a photo as evidence**. Open Keepsake, tap an item, and see the photo. Or press **Voice**, say "my water bottle", and hear where it was.

Built for HackHarvard 2026. Everything runs on your own computer.

## How it works

```
camera ─► OpenCV ─► YOLO11n + ByteTrack ─► area (from Scan room: Bed, Couch, Chair 1, …)
            │                                  │
            └─ frame differencing (motion) ────┤
                                               ▼
              per-object state machine: STABLE → POSSIBLE_CHANGE → MOVING → SETTLING → CONFIRMED
                                               │ (only after the object holds still)
                         SQLite (objects, events, snapshots) + JPEG photo on disk
                                               │
     React app (List · Map · Voice · Reposition) ◄── FastAPI on 127.0.0.1:8000
```

- **Detection:** Ultralytics **YOLO-World** (`yolov8s-worldv2`), an open-vocabulary YOLO prompted with each item's name, so it can find things outside COCO such as keys, wallets, AirPods and glasses. It runs at 1280 px wide, about 5 fps, on the GPU when available (Apple MPS or CUDA, falling back to the CPU). The higher resolution matters: across a room, items are too small to detect at 640. There's no training, no cloud vision, and no YOLO-World.
- **Tracked items** (in [backend/catalog.py](backend/catalog.py)): Phone, Water Bottle, Keys, Wallet, AirPods, Glasses, Laptop, Cup, Book, Backpack, Remote, Mouse. The app assumes one of each. Each item has its own confidence threshold (`min_conf`), because open-vocabulary scores vary by prompt. Short prompts work best ("bottle" scores about 0.7, "water bottle" about 0.36).
- **Room areas come from Scan room**, not a fixed layout. Keepsake runs the larger YOLO11m model over a few steady frames and proposes an area for each piece of furniture it reliably sees: bed, couch, chair, table, TV, sink, fridge, oven, microwave, toilet and bench. You review the proposal and can rename ("Table" → "Desk"), resize, delete or add areas (COCO has no dresser, shelf or ottoman class). An item gets the most specific area it sits in, "near the <area>" if it's just outside one, or the left/middle/right of the room if there are no areas.
- **When a photo is taken:** an item must be seen first (first sighting), moved to another area, or moved more than `CTRLF_MOVE_THRESHOLD` (6% of the frame) within the same area. It must then **settle**: stay within a small radius for `CTRLF_SETTLE_SECONDS` (0.8 s) and at least `CTRLF_STABILITY_FRAMES` frames, with little motion around it. Only then does Keepsake update the location and save a photo. It picks the clearest frame from that settled window, skipping frames where a detected person covers the item.
- **What doesn't trigger a photo:** someone walking past, jitter, an item picked up and put back in the same spot, or a brief misdetection.
- **Leaving view:** the last confirmed place and photo are kept, and the item shows **Out of view**. If it was mid-move when it vanished, Keepsake says so instead of claiming it's still there.
- **Photos:** full camera frames, with the item's box stored as metadata and highlighted in the app. Each item keeps its 20 most recent (`CTRLF_SNAPSHOT_RETENTION`). Photos taken within 3 s of each other at the same spot are skipped as duplicates. Photos are written by a background thread, so detection never waits on the disk.

## Install

```bash
cd ~/Projects/ctrl-f-spatial-memory
python3.12 -m venv .venv            # or: uv venv --python 3.12 .venv
.venv/bin/pip install -r backend/requirements.txt
npm --prefix frontend install
```

Model weights download on first use: `yolov8s-worldv2.pt` (about 25 MB) plus OpenAI CLIP (about 340 MB, cached by the `clip` package) for tracking, and `yolo11m.pt` (about 40 MB) the first time you scan the room. CLIP is installed by `requirements.txt`; without it, the camera panel shows "YOLO-World needs CLIP".

## Run

Start the backend from **Terminal or iTerm**, not from an IDE or agent app. macOS grants camera access per app.

```bash
cd ~/Projects/ctrl-f-spatial-memory/backend && ../.venv/bin/python main.py
```

```bash
npm --prefix ~/Projects/ctrl-f-spatial-memory/frontend run dev
```

Open http://127.0.0.1:5173. For voice, use Chrome, Edge or Safari.

### Choosing the camera (macOS)

```bash
cd backend && ../.venv/bin/python check_camera.py 0     # triggers the permission prompt; try 1, 2…
```

Camera numbers change: macOS numbers the cameras it sees right now, so with the iPhone connected it's usually 0 and the built-in camera 1, and without it the built-in camera is 0. Pick the camera by name instead (`check_camera.py` with no argument lists them):

```bash
cd backend && ../.venv/bin/python check_camera.py
cd backend && CTRLF_CAMERA_NAME=iPhone ../.venv/bin/python main.py
```

With a name set, Keepsake waits for that camera instead of opening another one. Or set `CTRLF_CAMERA_INDEX`:

```bash
cd backend && CTRLF_CAMERA_INDEX=1 ../.venv/bin/python main.py
```

For Continuity Camera, keep the iPhone locked and still, with its **back** camera facing the room. The phone shows "Connected to …" but no preview; the picture only appears on the Mac. If the app warns about black frames, restart the backend.

## Using it

- **List (home):** every item, with its latest photo, last-seen place, time and status. Tap one for the full photo with the item highlighted, the exact time, notes, and earlier photos.
- **Map:** the same data drawn on a room sketch. Solid markers are in view now, dashed ones are last-seen, and amber ones were last seen before the camera moved. Positions are approximate.
- **Voice:** press Voice. Keepsake asks "What are you looking for?", listens, answers from its stored memory ("I last saw your water bottle on the desk at 3:42 PM…") and opens the item's photo. Typing works too.
- **Scan room** (top right): do this once at setup and whenever you move the camera. Monitoring pauses, so moving the camera never counts as items moving.
  1. Aim the camera and hold it still.
  2. Press **Scan**. Keepsake detects the furniture and shows its proposed areas over a still photo.
  3. Rename, adjust, delete or add areas, then press **Save and resume**.

  Old photos and locations are kept and marked "Not rechecked since scan". When an item is seen again it's **reconfirmed**: you get a fresh photo, but it isn't logged as a move. If the whole view shifts unexpectedly, Keepsake briefly stops updating and suggests scanning again.
- **Settings → Customize voice** (gear icon, top right): pick the **Grok voice** (xAI text to speech: Eve, Ara, Rex, Sal, Leo or any voice your account lists) or the browser's built-in voice, set the speed (0.7–1.5×), and press **Preview**. Grok needs `XAI_API_KEY` (an `xai-…` key from [console.x.ai](https://console.x.ai)) in the repo's `.env`; restart the backend after adding it. If Grok fails, Keepsake falls back to the browser voice.
- **Privacy panel:** pause photo saving (locations still update), or clear all memories and photos.

## Configuration

All settings are optional environment variables, read at backend start. See [.env.example](.env.example).

| Variable | Default | Meaning |
|---|---|---|
| `CTRLF_CAMERA_INDEX` | `0` | Camera index, or a video file path for testing (video files loop) |
| `CTRLF_CAMERA_NAME` | unset | Pick the camera by name, e.g. `iPhone` (macOS). Wins over the index |
| `CTRLF_CAMERA_ENABLED` | `1` | `0` runs the API with no camera |
| `CTRLF_DETECT_CONFIDENCE` | `0.15` | Detector candidate cutoff. Items then need their own `min_conf` from catalog.py |
| `CTRLF_MODEL` | `backend/models/yolov8s-worldv2.pt` | Detector. A COCO model (`yolo11n.pt`) also works, but can't see keys, wallets, AirPods or glasses |
| `CTRLF_INFERENCE_FPS` | `5` | Detection rate |
| `CTRLF_INFERENCE_WIDTH` | `1280` | Detection resolution. Lower it (e.g. 640) on slow CPUs if items are close to the camera |
| `CTRLF_DEVICE` | auto | `mps`, `cuda` or `cpu`. Defaults to the GPU if there is one |
| `CTRLF_STABILITY_FRAMES` | `4` | Minimum settled frames before confirming |
| `CTRLF_SETTLE_SECONDS` | `0.8` | How long an item must hold still |
| `CTRLF_MOVE_THRESHOLD` | `0.06` | Same-area distance (fraction of frame) that counts as a move |
| `CTRLF_ABSENCE_SECONDS` | `2.0` | Time unseen before an item is marked out of view |
| `CTRLF_SNAPSHOT_RETENTION` | `20` | Photos kept per item |
| `CTRLF_SNAPSHOT_COOLDOWN` | `3` | Seconds within which a same-spot photo counts as a duplicate |
| `CTRLF_SNAPSHOT_DIR` | `backend/data/snapshots` | Where photos are stored (git-ignored) |
| `CTRLF_DB_PATH` | `backend/data/ctrlf.db` | SQLite file (git-ignored) |
| `CTRLF_REGIONS` | `backend/regions.json` | Room areas, written by Scan room (ships empty) |
| `CTRLF_SCAN_MODEL` | `backend/models/yolo11m.pt` | Larger model used only for furniture detection during a scan |
| `CTRLF_CAMERA_MODE` | `wearable` | `wearable` (chest-mounted phone): no movement claims from screen position, no camera-shift pause. `fixed`: the original room camera |
| `CTRLF_HANDS` | `1` | `0` turns off MediaPipe hand detection (interaction events) |
| `CTRLF_HAND_MODEL` | `backend/models/hand_landmarker.task` | MediaPipe hand model (see hands.py for the download command) |
| `CTRLF_ITEMS_MODEL` | `backend/models/items.pt` | Optional detector trained on our demo items (keys, wallet, AirPods, glasses) |

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Camera status, mode, capture setting, live detections |
| GET | `/api/catalog` | The eight items and their aliases |
| GET | `/api/objects` | All eight items in one canonical shape, including the latest photo (used by List, Map and Voice) |
| GET | `/api/objects/{id}` | One item, by id (`bottle_01`) or name (`phone`) |
| GET | `/api/objects/{id}/snapshots` | Photo history |
| GET | `/api/snapshots/{id}/image` | The photo (by id only, never by path) |
| GET | `/api/events` | Movement history |
| GET | `/api/observations` | Wearable observation events, newest first (`limit`, `after_seq`, `event_type`, `object_id`) |
| GET | `/api/observations/contract` | The event schema (fields, event types, evidence codes, version) |
| POST | `/api/query` | `{"text": "my water bottle"}` → `{found, answer, object}` |
| GET/PUT | `/api/settings` | `{"capture_enabled": bool}` |
| DELETE | `/api/memory` | Forget everything and delete all photos |
| POST | `/api/reposition/{start,cancel,finish,resume}` | Scan room: pause → scan → resume |
| GET | `/api/calibration/reference` | Steady reference photo from the last scan (kept in memory) |
| GET/PUT | `/api/regions` | Read or save room areas (`{name, kind, camera}`) |
| GET/PUT | `/api/voice` | Voice settings `{provider, voice_id, speed}`, plus available Grok voices |
| POST | `/api/tts` | `{"text": …}` → MP3 in the Grok voice (key stays server-side) |
| GET | `/api/camera/frame` | Newest annotated frame as one JPEG (the dashboard polls this about 5×/s) |
| GET | `/api/camera` | Live annotated MJPEG stream (kept for other clients) |

## Tests

```bash
.venv/bin/python -m pytest
npm --prefix frontend run build
```

There are 65 backend tests, all using **synthetic** detections and frames. They cover:

- the catalog and its aliases
- first sightings, moves between areas and moves within an area
- jitter and brief flicker, unrelated motion and passers-by, person occlusion
- items leaving view (including mid-move) and missing detections
- snapshot creation, duplicate suppression, retention, persistence and deletion
- the capture toggle, query answers, and list/detail consistency
- furniture proposals from scan detections, and adaptive area/"near"/side-of-room wording
- the full Scan room flow, including preserving history and no false moves
- wearable observation events: flicker, ID swaps, occlusion, camera motion, duplicate frames, cooldown, no movement claims
- hand evidence: hand passing by, hand covering an item, camera pan, pickup then put-down, item leaving with the hand
- the observation event contract, its storage, and `/api/observations`

These tests check the logic, not real-world perception accuracy. See the live checklist below.

### Live test checklist (real camera)

1. **Placement:** put a bottle on the Desk area and wait about 1 s. The card shows a photo, "Desk", "In view now".
2. **Move:** move it to another area, or more than about 1/16 of the frame within the Desk. A new photo appears and Recent activity logs the move.
3. **Walk-by:** walk through the frame without touching anything. No new photos.
4. **Disappearance:** take the bottle away. It keeps its last photo and shows "Out of view".
5. **Voice:** press Voice and say "my water bottle". You hear the answer and the photo opens.
6. **Scan room:** press Scan room, move the camera if you like, then Scan. Check the proposed areas match your furniture, fix them, and Save and resume. There should be no new movement events, and old photos remain.

## Wearable observation events (issues #4, #5)

With the phone worn on the chest, screen position says nothing about whether an item moved. So the
worker also emits **observation events** for Photon reminders and voice, stored in SQLite and served by
`GET /api/observations`. The contract lives in `backend/events.py`, which uses only the standard library,
so consumers never need the vision stack. Each event has `event_id, event_type, object_id, category, name,
timestamp, confidence, bbox, snapshot_id, frame_id, camera_mode, view_id, evidence[]` plus a `seq` cursor.

| event_type | Emitted when | What it does **not** claim |
|---|---|---|
| `object_observed` | Item seen in ≥3 of the last 5 camera-steady frames, at a consistent position (one per item per 30 s, with a photo) | that it moved or was placed |
| `interaction_candidate` | A MediaPipe hand stays on the item's box for 2+ frames | that it was picked up |
| `possible_pickup` | Next, the item moves with the hand, or vanishes and stays gone after the hand leaves (not if it reappears in place, which is occlusion) | that the user still has it |
| `placement_confirmed` | Only after a `possible_pickup`: the item reappears, with no hand on it, still for 5 frames, camera steady (with a photo) | — |

Filters: tracker ID swaps (events are keyed by item, not track id), flicker and jumping false hits,
brief occlusion (2 s grace), camera motion (measured outside the hand/object boxes; any pan resets
partial evidence), duplicate or out-of-order frames, and a per-item cooldown. Hand detection is optional:
`pip install mediapipe`, download the model (command in `backend/hands.py`), and `/api/health` reports
`hands: on`. Without it, only `object_observed` is emitted.

In `wearable` mode the memory never reports `moved`/`moved_within`. A re-sighting somewhere else is
`reconfirmed`, so the item's last-seen place updates without inventing a movement event.

### Wearable validation checklist (chest-mounted iPhone)

1. `/api/health` shows `camera_mode: wearable` and `hands: on` (or the reason in `hands_reason`).
2. **Seen:** look down at the keys on a table for about 1 s. You get one `object_observed` with a photo, and no `moved` event appears under Recent activity.
3. **Walk around:** turn and walk past the keys. You should get no duplicate events within 30 s and no `possible_pickup`.
4. **Hand passes:** wave your hand over the keys without touching them. You get nothing, or at most `interaction_candidate`.
5. **Pick up and put down:** pick the keys up, carry them, and set them down elsewhere while looking at them, then let go and hold still for about 1 s. You should see `interaction_candidate`, then `possible_pickup`, then `placement_confirmed` with a photo of the new spot.
6. **Occlusion:** cover the keys with your hand and lift it away. There should be no `possible_pickup`.
7. Note each failure (missed hand, false pickup, item not detected) and its lighting and distance. Thresholds are in `wearable.py`.

## Privacy

- Camera footage is processed locally. Keepsake saves selected object-memory photos, not a continuous video recording.
- Photos are full frames, so they can show whatever else is in the room. They stay in `backend/data/snapshots/` (git-ignored) and are never uploaded.
- Live frames exist only in memory: the preview stream, a ring buffer of about 2.5 seconds used to pick photo frames, and the calibration reference.
- SQLite stores item names, areas, approximate positions, times, confidence and photo metadata. Even this metadata can reveal routines.
- You can pause photo saving or clear everything from the Privacy panel.
- The backend listens on 127.0.0.1 only. Ultralytics telemetry is turned off, and there are no analytics.
- With the Grok voice on, the sentence being spoken (e.g. "I last saw your keys on the desk") is sent to xAI to turn into audio. No images, video or microphone audio are sent. The API key stays in `.env` on the backend and is never sent to the browser.
- Voice recognition runs in your browser. In Chrome, speech audio is processed by Google. Typed questions stay local.

## Troubleshooting

| Symptom | Fix |
|---|---|
| "Camera unavailable" | Start the backend from Terminal and run `check_camera.py` to grant permission |
| Camera pops up on your iPhone, then disappears | Pick the camera with `CTRLF_CAMERA_NAME=iPhone` |
| Sometimes the iPhone, sometimes the Mac camera | Use `CTRLF_CAMERA_NAME=iPhone`; indexes shift when the iPhone connects or drops |
| "The camera is sending black frames" | Uncover the lens or restart the backend (Continuity Camera sometimes connects black) |
| "The camera view changed a lot" | If you moved the camera, press Scan room |
| Scan missed a piece of furniture | Add it by hand in the review step. Pretrained COCO has no dresser, shelf, desk or ottoman class, and tables show up as "Table" |
| "Keepsake is already running" | Another backend owns port 8000. Stop it with Ctrl+C in its window. A second copy must not share the camera and database |
| No photo after moving an item | Let go and wait about 1 s. Photos are taken only once the item holds still and your hand is clear |
| Item not detected | Check `/api/health` shows `inference_width` 1280 and a GPU `device`. Improve the lighting or move it closer, or lower `CTRLF_CONFIDENCE` to 0.3. Small items (mouse, remote) are harder |
| Live view frozen but items still update | Reload the page. The view polls single frames and shows "Live view paused" if frames stop arriving |
| Voice button says unsupported | Use Chrome, Edge or Safari, or type instead |

## Not built (stretch goals)

- **Hand-object interaction (MediaPipe):** not implemented. Keepsake infers interaction only from an item's own movement, and never claims an item was touched if it didn't move.
- **3D room view:** not implemented. YOLO provides no room geometry or camera pose. A real 3D room would need something like an Apple RoomPlan export from a LiDAR iPhone, converted to a Three.js scene. Nothing in the app fakes a 3D scan.
