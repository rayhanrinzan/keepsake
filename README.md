# Keepsake

> *Your room remembers, so you don't have to.*

Keepsake sees six everyday items through a chest-worn iPhone and remembers **when each was last seen, with a photo as evidence**. Tap an item to see the photo, press **Voice** and say "my keys", or get a gentle iMessage reminder about something you just put down.

Built for HackHarvard 2026. Vision and memory run on your own computer. It's a prototype for memory support, not a clinically validated device.

The repo also holds **[lastseen-wearable/](lastseen-wearable/README.md)**, Roman's separate "Last Seen" app. It has its own camera loop, memory and dashboard, and also uses port 8000, so run one app at a time.

## How it works

```
iPhone (Continuity Camera) ─► OpenCV ─► YOLO-World + items.pt (trained) ─┬─► memory (last sighting per item)
                                  │            + MediaPipe/YOLO hands      ├─► observation events + photos (SQLite)
                                  └─ frame differencing (camera motion) ───┘            │
                                                                                        ▼
   React app (Items · Settings · Voice) ◄── FastAPI on 127.0.0.1:8000 ──► reminder engine ─► Photon agent ─► iMessage
```

- **Detection:** Ultralytics **YOLO-World** (`yolov8s-worldv2`), an open-vocabulary model prompted with each item's name, plus our own **`backend/models/items.pt`** trained on about 1,200 photos of the demo items (keys, wallet, AirPods case and glasses; mAP50 about 0.98). It runs at 1280 px, about 5 fps, on the GPU when there is one (Apple MPS or CUDA).
- **Tracked items** (in [backend/catalog.py](backend/catalog.py)): Water Bottle, Keys, Wallet, AirPods, Glasses, Backpack. The app assumes one of each. Each has its own confidence threshold (`min_conf`).
- **Worn camera only:** where an item appears on screen depends on where you happen to be looking, not where it is. So Keepsake never names a room area, pins items on a map, or claims an item moved. It keeps the **time and photo** of the last real sighting, and whether the item is in view right now.
- **Observation events** (wearable): an item seen steadily gives `object_observed` with a photo. A hand on an item, then moving it and setting it down, gives `interaction_candidate` → `possible_pickup` → `placement_confirmed`. See [Wearable observation events](#wearable-observation-events-issues-4-5).
- **When a photo is taken:** with each `object_observed` (an item seen steadily, at most once per item every 30 s) and each `placement_confirmed`. A single-frame false hit never counts: memory needs `CTRLF_STABILITY_FRAMES` detections within `CTRLF_SETTLE_SECONDS`.
- **Photos:** full camera frames, with the item's box highlighted in the app. Each item keeps its 20 most recent (`CTRLF_SNAPSHOT_RETENTION`). A background thread writes them, so detection never waits on the disk.

## Install

```bash
cd ~/Projects/ctrl-f-spatial-memory
python3.12 -m venv .venv            # or: uv venv --python 3.12 .venv
.venv/bin/pip install -r backend/requirements.txt
npm --prefix frontend install
```

Model weights download on first use: `yolov8s-worldv2.pt` (about 25 MB) plus OpenAI CLIP (about 340 MB, cached by the `clip` package). `backend/models/items.pt` comes with the repo. CLIP is installed by `requirements.txt`; without it, the camera panel shows "YOLO-World needs CLIP".

Optional extras:

```bash
cp .env.example .env                         # then fill in XAI_API_KEY for the Grok voice
.venv/bin/pip install mediapipe              # hand evidence for pickup/put-down
curl -L -o backend/models/hand_landmarker.task \
  https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task
npm --prefix integrations/photon install     # iMessage reminders (see integrations/photon/README.md)
```

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

`CTRLF_CAMERA_NAME` matches part of the name macOS shows, so use whatever `check_camera.py` lists. A phone renamed to "Sam's iPhone 2" still matches `iPhone`; a typo in the phone's name has to be typed the same way.

For Continuity Camera, keep the iPhone **locked** and still, back camera facing out. The phone shows "Connected to …" but no preview; the picture only appears on the Mac. While the phone is unlocked or in use, macOS sends black or frozen frames, so lock it again if the Settings camera view goes black.

## Using it

The sidebar has two views (a bottom bar on phones):

- **Items** (home): every item with its latest photo, when it was last seen and whether it's in view, the **Voice** button, the search box and recent activity. Tap an item for the full photo, the exact time and earlier photos. Say "where are my keys?" hands-free after the first click.
- **Voice:** press Voice. Keepsake asks "What are you looking for?", listens, answers from its stored memory ("I last saw your keys at 3:42 PM. The last photo is in Keepsake.") and opens the item's photo. Typing works too.
- **Settings:**
  - **Camera:** the live view.
  - **Privacy:** pause photo saving, or clear all memories and photos.
  - **Customize voice:** the **Grok voice** (xAI text to speech) or the browser voice, the speed (0.7–1.5×), and **Preview**. Grok needs `XAI_API_KEY` (an `xai-…` key from [console.x.ai](https://console.x.ai)) in the repo-root `.env`; restart the backend after adding it. `.env` is git-ignored, so **each teammate needs the key in their own `.env`** (share it privately, never in git). Without it the app silently uses the browser voice. `GET /api/voice` shows `grok_available`.
- **iMessage reminders:** opt in from an authorized phone by texting "high assistance" or "everyday" to the Photon number. See [integrations/photon/README.md](integrations/photon/README.md).

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
| `CTRLF_STABILITY_FRAMES` | `3` | Detections needed (within `CTRLF_SETTLE_SECONDS`) before an item counts as seen |
| `CTRLF_SETTLE_SECONDS` | `1.0` | Window for those detections |
| `CTRLF_ABSENCE_SECONDS` | `2.0` | Time unseen before an item is marked out of view |
| `CTRLF_SNAPSHOT_RETENTION` | `20` | Photos kept per item |
| `CTRLF_SNAPSHOT_COOLDOWN` | `3` | Seconds within which a same-spot photo counts as a duplicate |
| `CTRLF_SNAPSHOT_DIR` | `backend/data/snapshots` | Where photos are stored (git-ignored) |
| `CTRLF_DB_PATH` | `backend/data/ctrlf.db` | SQLite file (git-ignored) |
| `CTRLF_HANDS` | `1` | `0` turns off MediaPipe hand detection (interaction events) |
| `CTRLF_HAND_MODEL` | `backend/models/hand_landmarker.task` | MediaPipe hand model (see hands.py for the download command) |
| `CTRLF_ITEMS_MODEL` | `backend/models/items.pt` | Optional detector trained on our demo items (keys, wallet, AirPods, glasses) |

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Camera status and warnings (black or frozen feed), capture setting, live detections, hands |
| GET | `/api/catalog` | The six items and their aliases |
| GET | `/api/objects` | All items in one canonical shape, including the latest photo (used by List, Map and Voice) |
| GET | `/api/objects/{id}` | One item, by id (`bottle_01`) or name (`keys`) |
| GET | `/api/objects/{id}/snapshots` | Photo history |
| GET | `/api/snapshots/{id}/image` | The photo (by id only, never by path) |
| GET | `/api/events` | Recent activity: observation events, newest first |
| GET | `/api/observations` | Wearable observation events, newest first (`limit`, `after_seq`, `event_type`, `object_id`) |
| GET | `/api/observations/contract` | The event schema (fields, event types, evidence codes, version) |
| POST | `/api/query` | `{"text": "my water bottle"}` → `{found, answer, object}` |
| GET/PUT | `/api/settings` | `{"capture_enabled": bool}` |
| DELETE | `/api/memory` | Forget everything and delete all photos |
| GET/PUT | `/api/voice` | Voice settings `{provider, voice_id, speed}`, plus available Grok voices |
| POST | `/api/tts` | `{"text": …}` → MP3 in the Grok voice (key stays server-side) |
| GET | `/api/camera/frame` | Newest annotated frame as one JPEG (the dashboard polls this about 5×/s) |
| GET | `/api/camera` | Live annotated MJPEG stream (kept for other clients) |
| GET/PUT | `/api/reminders/settings` | Reminder mode, opt-in, watched items, per-mode overrides, per-item state |
| POST | `/api/reminders/check` | Manual or "heading out" check over real memory (writes need `X-Keepsake-Local: 1`) |
| GET | `/api/reminders/alerts` | Queued reminders; `POST …/{id}/claim` and `…/{id}/result` for the Photon agent |
| POST | `/api/reminders/events`, `/api/reminders/ack` | Extra event producers; I have it / snooze / pause / resume |

## Tests

```bash
.venv/bin/python -m pytest                       # 142 tests
KEEPSAKE_HTTP_E2E=1 .venv/bin/python -m pytest    # + real loopback HTTP / TypeScript bridge
npm --prefix frontend run build
cd integrations/photon && npm test && npm run typecheck
```

Every test uses **synthetic** detections, frames and events. They cover memory, snapshots, catalog and queries, wearable observation events and hand evidence (including camera wobble), the reminder engine for both modes, the Photon agent, Grok voice settings, `.env` parsing, and an end-to-end bridge from Python to the TypeScript agent and React list. They check logic, not real-world perception accuracy.

`scripts/demo_preflight.py` and `scripts/camera_diagnostic.py` check a running backend read-only before a demo.

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
brief occlusion (2 s grace), camera motion (measured outside the hand/object boxes; up to 2 unsteady
frames in a row are skipped, a longer pan resets partial evidence), duplicate or out-of-order frames,
and a per-item cooldown.

**Hands** come from MediaPipe (optional; see Install) **and** YOLO-World's "hand" prompt, merged. From a
chest mount, hands are often only partly in view at the bottom edge, where MediaPipe rarely fires, so
**tilt the mount down** until the table and your hands show in the Settings camera view.
`/api/health` reports `hands` (on/unavailable) and `hands_in_view` per frame. Without any hand
source, only `object_observed` is emitted.

Memory never reports movement: seeing an item somewhere else on screen just updates when it was last
seen.

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
| "The camera is sending black frames", or the live view is black/frozen | Lock the iPhone and keep it still: Continuity Camera pauses while the phone is unlocked or in use. Otherwise uncover the lens or restart the backend |
| `Camera "iPhone" isn't connected (cameras now: …)` | Set `CTRLF_CAMERA_NAME` to part of a name in that list, and install `pyobjc-framework-AVFoundation` (in requirements) if the list is empty |
| Grok voice not used | `GET /api/voice` shows `grok_available`. Put `XAI_API_KEY=xai-…` in the repo-root `.env` and restart the backend |
| Scan missed a piece of furniture | Add it by hand in the review step. Pretrained COCO has no dresser, shelf, desk or ottoman class, and tables show up as "Table" |
| "Keepsake is already running" | Another backend owns port 8000. Stop it with Ctrl+C in its window. A second copy must not share the camera and database |
| No photo after moving an item | Let go and wait about 1 s. Photos are taken only once the item holds still and your hand is clear |
| Item not detected | Check `/api/health` shows `inference_width` 1280 and a GPU `device`. Improve the lighting, hold the camera steadier, or move closer. Blurry frames from a moving chest camera are the most common cause |
| Live view frozen but items still update | Reload the page. The view polls single frames and shows "Live view paused" if frames stop arriving |
| Voice button says unsupported | Use Chrome, Edge or Safari, or type instead |

## Not built yet

- **End-to-end hand evidence on the worn camera:** the pipeline exists and is tested on synthetic sequences, but a live pickup/put-down hasn't produced events yet, mostly because hands are out of frame from a chest mount. Reminders work today from photo-backed sightings.
- **Where in the room:** a worn camera can't place items in the room. That would need real room geometry (for example an Apple RoomPlan scan plus phone tracking); nothing in the app fakes it.
- **Several of the same item**, and items beyond the six in the catalog.
