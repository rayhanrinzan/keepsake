# CLAUDE.md — Keepsake

## Concept
Keepsake (repo: rayhanrinzan/keepsake) is a local visual-memory assistant for HackHarvard 2026. A
chest-worn iPhone (Continuity Camera) sees six items. Keepsake keeps the last real sighting of each
**with a photo**, answers "where are my keys?" (typed, hands-free voice, Grok TTS), and can text gentle
reminders through Photon Spectrum iMessage. It is **wearable-only**: a worn camera's screen position is not
a room position, so there are no room areas, maps or movement claims; answers cite time and photo.
Prototype for memory support, not a clinically validated device.

The repo also contains `lastseen-wearable/`, Roman's separate "Last Seen" app (PR #11): its own camera
loop, CLIP item identity, Whisper voice and dashboard. It does not share code, DB or API with Keepsake and
also binds port 8000, so run one or the other.

## Architecture (Keepsake)
- `backend/catalog.py`: the 6 items (Water Bottle `bottle`, Keys `car key`, Wallet, AirPods `airpods case`,
  Glasses `glasses`, Backpack), aliases, icon, per-item `min_conf`. Single source of truth; categories
  match the trained model's class names.
- `backend/vision.py`: `VisionWorker` thread. Camera (by name via `cameras.py`, or index) → 1280 px →
  `MotionDetector` → YOLO-World track (`set_classes(catalog + person + hand)`) plus `models/items.pt`
  (trained keys/wallet/AirPods/glasses, committed) → `memory.observe` → wearable observer and
  `InteractionDetector` with hands = MediaPipe ∪ YOLO-World "hand" (`merge_hands`). Records
  observation events + photos, MJPEG preview, black-frame/camera-shift warnings, `hands_in_view`.
- `backend/events.py` (stdlib only): observation event contract (`object_observed`,
  `interaction_candidate`, `possible_pickup`, `placement_confirmed`; `evidence[]`; `validate_event`).
- `backend/wearable.py`: `WearableObserver` (#4) and `InteractionDetector` (#5, skips up to
  `motion_grace` unsteady frames; sustained motion resets). Pure Python, synthetic-sequence tests.
- `backend/hands.py`: optional MediaPipe `HandDetector` (Tasks API, VIDEO mode, conf 0.3,
  `models/hand_landmarker.task`, git-ignored). Missing means disabled, never an error.
- `backend/memory.py`: `ItemMemory`: per item, the last real sighting (`stability` detections within
  `settle_seconds`), in view or not, confidence. No area, position or move events. `answer_query()` is
  deterministic and cites time and photo.
- `backend/main.py`: FastAPI on 127.0.0.1. `object_view()` is the canonical object shape (no `region`, `x`,
  `y`): it merges memory with the latest observation and its photo. `/api/events` = recent observation
  events. `CTRLF_*` env vars, plus the repo-root `.env` via `voice.load_env_file` (strips inline comments).
- `backend/reminders.py` + `reminders_api.py`: smart reminders. One policy engine, presets
  `high_assistance` / `everyday` (`off` by default; explicit opt-in). Reads the observations table by
  `seq` on its own thread; due when the item is out of view for the delay, or on "heading out"; a dark,
  frozen or disconnected camera cancels. Queued alerts are claimed and re-validated before delivery.
- `backend/presence.py` (Roman): person presence; its counter is reported as 0 (other people leaving a
  worn camera's view isn't the wearer leaving).
- `backend/describe.py`: `SceneDescriber`: on a lookup, the item's newest photo (box drawn on) goes to a
  Grok vision model for one sentence of reference points ("It was on a green seat next to…"); cached per
  photo; any failure means no sentence. `CTRLF_DESCRIBE=0` off. `scripts/try_describe.py` tries it.
- `backend/voice.py`: Grok TTS (`XAI_API_KEY`), `/api/voice`, `/api/tts`.
- Also: `snapshots.py` (JPEG writer, retention, dedupe), `database.py` (SQLite: objects, snapshots,
  observations, settings; the legacy `events` table and region columns are no longer written).
- `vision.py` warns on black frames and on a frozen feed (exactly zero change for 5 s).
- `backend/verify.py`: `ClipVerifier` second opinion on every item's boxes (all six) (item vs its
  look-alikes, from real false hits); verdicts cached 1 s per item; when on, YOLO-World also proposes the
  trained items as a backup. `CTRLF_VERIFY=0` disables it; if CLIP can't load, boxes pass unchanged.
  `big_enough` first drops item boxes under `CTRLF_MIN_ITEM_AREA` (0.004) of the frame.
- `frontend/src`: React 19, Vite, Tailwind 4. Amy's layout: `Sidebar` (Items / Settings; bottom bar on
  phones). Items: `SearchPanel` (voice, hands-free wake phrase, typed), `CameraPanel`, `ObjectList`,
  `ObjectDetail`, `ActivityFeed`. Settings: `CameraPanel`, `PrivacyPanel`, `SettingsDialog` (Customize
  voice). `App.tsx` polls every 1.5 s.
- `integrations/photon/`: TypeScript Photon Spectrum agent (`spectrum-ts` 12.11): polls
  `/api/reminders/alerts`, claims, checks its own E.164 allowlist (`.env`, git-ignored), sends, reports
  `accepted`/`failed` (accepted ≠ delivered). Inbound commands: modes, I have it, remind me later,
  pause/resume, heading out, "where is my …". See its README and EVENTS.md.
- `scripts/demo_preflight.py`, `scripts/camera_diagnostic.py`: read-only checks of a running backend.

## Run
```bash
cd backend && CTRLF_CAMERA_NAME=iPhone ../.venv/bin/python main.py   # from Terminal; name = what macOS shows
npm --prefix frontend run dev                                          # http://127.0.0.1:5173
cd integrations/photon && npm run start                                # reminders (needs its .env)
cd backend && ../.venv/bin/python check_camera.py                      # list cameras by name
```
`main.py` refuses to start if port 8000 is taken and uses a 3 s graceful-shutdown timeout (the MJPEG
stream never closes). Agent sessions can't get camera permission: launch the backend in Terminal.app,
e.g. `open -a Terminal some.command`. Stop it by killing only the listener
(`lsof -ti tcp:8000 -sTCP:LISTEN`); killing every user of port 8000 also kills the Vite proxy.
Continuity Camera sends black/frozen frames while the phone is unlocked or in use: lock it on the mount.

## Test
```bash
.venv/bin/python -m pytest                    # 142 tests, synthetic data; pythonpath=backend
KEEPSAKE_HTTP_E2E=1 .venv/bin/python -m pytest # + real loopback HTTP/TypeScript bridge
npm --prefix frontend run build
cd integrations/photon && npm test && npm run typecheck
cd lastseen-wearable && .venv/bin/python -m pytest   # Roman's app, its own venv (requirements.txt)
```
`tests/conftest.py` has `Clock` and `obs()`. API tests point `CTRLF_*` at tmp paths.

## Conventions
- Never fabricate detections, photos or locations in live mode. Synthetic data belongs only in tests.
  Never turn a screen position into a room location; there are no room areas.
- Never commit DBs, photos, frames, weights or secrets (`backend/data/`, `*.pt`, `*.task`, `.env`).
  **One exception:** `backend/models/items.pt` is committed so the team shares the trained model
  (agreed in PR #10). Keep it the only weights file in git.
- Seeing an item somewhere else on screen is never a movement event.
- Reminders are off until an explicit opt-in; hand proximity is never contact; wording is "last seen".
- Work happens on feature branches. Don't push to main or merge without approval. `integration/merge-all`
  (PR #9) combines everyone's work.

## Limitations
- One item per category, six items. Detection is weaker on blurry, moving wearable frames.
- Hand evidence works only when hands are in frame; a chest mount usually shows fingertips at the bottom
  edge at best. Tilt the mount down. Live pickup/put-down has not yet produced events end to end.
- No "where in the room": that would need real room geometry (e.g. RoomPlan + phone tracking).
- Thresholds tuned on synthetic tests plus a few live runs. Polling, not push. Single user.

## Next priorities
1. Live-tune hand evidence on the worn camera (mount angle, `max_camera_motion`, YOLO-World hand conf).
2. Decide how Keepsake and Roman's Last Seen relate (one product, or keep separate).
3. Merge PR #9 into main after review.
4. Multi-instance items; real room placement from RoomPlan + phone tracking (stretch).
