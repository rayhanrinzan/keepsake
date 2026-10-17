# Last Seen

**A room that remembers, for people with early memory loss and their caregivers.**

An iPhone mounted high in a corner watches the room, and a laptop notices when a hand picks up or puts down one of your things. Ask "Where are my AirPods?" out loud or by text, and the room answers by voice with where it last saw them and when. A "memory frame" (an old phone or iPad on the wall) shows the snapshot with the item circled and a short clip of you putting it there. When the system is unsure, it says so instead of guessing.

This milestone tracks four items: AirPods, glasses, playing cards and a water bottle.

## How it works

Everything runs in one Python process on the laptop:

1. **Camera** (`lastseen/capture/`): the iPhone via Continuity Camera; only the latest frame is kept, so nothing lags.
2. **Vision** (`lastseen/vision/`): MediaPipe hands, a YOLO-World detector that proposes boxes, CLIP embeddings that decide which box is *your* item, a change detector that spots what appeared or vanished where a hand was, and a YOLO person tracker.
3. **Per-item tracker** (`lastseen/engine/`): a state machine per item (PLACED, HELD, CARRIED_OUT, ...) with debouncing; places are named by zones in `zones.json`. Touch-to-track locks onto an item the first time a hand handles it.
4. **Memory** (`lastseen/memory/`): SQLite for items, events and questions, plus a snapshot and a short clip per event.
5. **Answers** (`lastseen/brain/`): the location and state come from the database, never from an LLM. Answers are built from templates; an LLM (via Chalk) is optional for wording.
6. **Outputs**: voice in and out (`lastseen/voice/`, faster-whisper and macOS `say`), and a FastAPI server (`lastseen/server/`) for the dashboard, the memory frame, a live MJPEG stream and a WebSocket event bus.

## How to run

macOS on Apple silicon, Python 3.11+.

```bash
uv venv && source .venv/bin/activate
uv pip install -r requirements.txt
python -m lastseen
```

- **Camera:** set `camera.source` in `config.yaml` to the camera's name (default `"iPhone"`, matched by name through Continuity Camera; a number or an `.mp4` path also work). `python -m lastseen.tools.list_cameras` lists what is connected. Keep the phone plugged in with auto-lock off.
- **Models:** YOLO, CLIP and Whisper weights download into `models/` on first run. The MediaPipe hand model must be downloaded once to `models/hand_landmarker.task` (the error message prints the URL).
- **Zones:** `python -m lastseen.tools.draw_zones` to click the surfaces (desk, tray, ...) on a frozen frame.
- **Pages:** open the dashboard on the laptop itself at `http://localhost:8000/dashboard`, and the wall frame from the phone at `http://<laptop-ip>:8000/frame`. Put the laptop and phones on one phone's hotspot (venue Wi-Fi often blocks device-to-device traffic). The dashboard, `/stream`, `/health.html` and every `POST /api/*` answer 403 to other devices; set `server.lan_dashboard: true` in `config.yaml` to open them to the LAN (the frame, `/ws`, `/clips` and `GET /health` are always open). `server.port` sets the port.
- **Touch-to-track:** pick up one of the configured items and put it down; it appears on the dashboard and its location is remembered from then on. Backup: "Backup controls" on the dashboard lets you click an item on the stream to enroll it, or forget it.
- **Ask:** say "where are my AirPods?", or type it in the dashboard's Ask box.
- **Reset between demo runs:** `python -m lastseen.tools.reset` (keeps item galleries and zones).
- Every feature has a switch under `features:` in `config.yaml`. `LASTSEEN_CONFIG` picks another config file and `LASTSEEN_PORT` another port.

## Where Chalk is used

Question parsing and answer wording can go through **Chalk's AI Router**, an OpenAI-compatible gateway. The client is `lastseen/brain/llm.py`. It is optional: set `CHALK_ROUTER_KEY`, `CHALK_API_HOST`, `CHALK_MODEL` (and `CHALK_ENV_ID` if needed) in `.env`. Without them, or when the router is slow or unreachable, the app uses its template answers. Only text is sent (the question, the item names, and the answer sentence with its item, state and zone), never images.

## Where Photon is used

**Not built yet.** Caregiver texts and calls through Photon (alerts with a snapshot, and texting back "where are her glasses?") are planned as Phase 9. The `features.photon` switch exists but does nothing yet.

## Privacy

- Video never leaves the laptop. Frames are processed in memory and are not written to disk.
- The only images saved are each event's snapshot and short clip in `data/clips/`, which are deleted after 24 hours.
- Microphone audio is transcribed locally and discarded; it is never stored.
- The only thing that leaves the laptop is text sent to Chalk (when configured): the question, the item names, and the answer's item, state and zone.

## Eval results

No eval numbers yet. The recorded-scenario eval harness (CLAUDE.md, Phase 10) is not built; we will only report numbers we measured.

## Credits

Built on Ultralytics YOLO, OpenAI CLIP, MediaPipe, Roboflow Supervision, faster-whisper, FastAPI, OpenCV and PyObjC. Inspired by reCall (Hack the North); Visiona was read as a reference. No code was copied from either. Licenses and details: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
