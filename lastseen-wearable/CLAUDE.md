# Last Seen — Build Instructions for Claude Code

> Put this file at the root of the repo. Claude Code reads `CLAUDE.md` automatically.
> Team: build in the phase order below. The demo loop (Phase 0–6) comes before everything else.

---

## 1. What we are building

**Last Seen** is a "room that remembers" for people with early memory loss and their caregivers.

- An **iPhone mounted high in a corner** streams video to a **laptop**.
- The laptop watches for the moment an object is **picked up or put down**, and logs where it went.
- Anyone in the room can ask out loud, **"Where's my inhaler?"**, and the room answers by voice.
- A **memory frame** (a second iPhone or an old iPad on the wall) shows a photo of the room with the item circled, plus a 3-second clip of the person putting it there.
- The system is **honest**: if an item vanished under a blanket, it says *"last seen going under the blanket on the bed"*, never a confident guess.
- **Proactive:** when the person heads for the door and a **critical item** (inhaler, EpiPen, pill organizer) is still in the room, it says *"Wait, your inhaler is still on the bed."*
- **Caregivers** are reached through **Photon** (a real phone number: iMessage/SMS texts, and a voice call). They can text back "where's her inhaler?" and get the answer.
- Question answering is routed through **Chalk's AI Router**, and we ship an **eval harness** that scores accuracy on recorded scenarios (for the Chalk prize).

**Hardware:** none beyond phones and one laptop (ideally a Mac with Apple silicon).

---

## 2. Ground rules for Claude Code

1. **Work phase by phase.** Finish a phase, run its acceptance check, commit, then move on. Never start Phase N+1 with Phase N broken.
2. **Keep `main` runnable at all times.** `python -m lastseen` must start the app after every commit.
3. **Every feature behind a config flag** in `config.yaml` (e.g. `features.search_sense: false`), so we can switch off anything flaky minutes before the demo.
4. **Deterministic core, LLM on the edges.** Where an item is, and its state, come from our database and state machine, never from an LLM's guess. The LLM only parses questions and phrases answers. If the LLM is unreachable, fall back to templates.
5. **Privacy invariant:** raw video frames never leave the laptop and are never written to disk, except short event clips and snapshots in `data/clips/` (auto-deleted after 24h). Only text (questions, answers, events) goes to Chalk and Photon, plus the one snapshot/clip we deliberately send to the caregiver.
6. **Don't invent APIs.** For Photon, Chalk, Ultralytics, and MediaPipe, check the current docs before writing integration code (links in §11). If something here contradicts the official docs, the docs win; note the change in `NOTES.md`.
7. **Ask the human before** adding a heavy dependency (>200 MB), changing the data model, or removing a feature.
8. **Log, don't crash.** Every background loop catches exceptions, logs them, and keeps running.
9. **Licensing:** see §3. Only copy code from repos whose license allows it, and keep their license notice with the copied code.

---

## 3. Reuse map: what to borrow instead of building

We are allowed to credit and reuse open-source work, **but crediting is not enough legally**: code is only reusable if its license permits it. Rules:

- **MIT / Apache-2.0 / BSD:** copy or adapt freely. Keep the original copyright + license text in a `THIRD_PARTY_NOTICES.md` and a comment at the top of each adapted file.
- **AGPL-3.0 (Ultralytics):** fine as a dependency for a public hackathon repo; our repo must also be public/open source.
- **No license file = all rights reserved.** Do **not** copy code. Ideas only.

| Source | License | What to take | How |
|---|---|---|---|
| [Visiona](https://github.com/paavansirivardhan123/Visiona) | MIT | Closest existing project: YOLO + ByteTrack loop, 15-min object memory, **custom object labeling with MobileNetV3 embeddings + cosine similarity** ("this is my water bottle"), push-to-talk mic capture with pre-warmed stream, LangChain tool routing, JSONL session logs, `core/config.py` single-source config | Read `core/memory.py`, `perception/tracker.py`, the FeatureDB/embedding code, `audio/voice_input.py`, `audio/speech.py`, `agents/tools/vision_tools.py`. Adapt the embedding re-ID and the mic capture. Do **not** take depth estimation, GPS, kinematics, or threat scoring; we don't need them. |
| [Ultralytics](https://github.com/ultralytics/ultralytics) | AGPL-3.0 | YOLO-World (open-vocabulary detection by text prompt), ByteTrack/BoT-SORT tracking, fine-tuning | `pip` dependency |
| [Roboflow Supervision](https://github.com/roboflow/supervision) | MIT | `PolygonZone`, box/label/polygon annotators for the dashboard overlay, `Detections` utilities | `pip` dependency |
| [MediaPipe](https://github.com/google-ai-edge/mediapipe) | Apache-2.0 | Hand landmarks (pick-up / put-down), pose (search sense, person at door) | `pip` dependency |
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper) | MIT | Local speech-to-text | `pip` dependency |
| [reCall](https://github.com/darryltanzil/reCall) | **No license** | Inspiration only (prior hackathon winner: webcam → GPT vision "comic strips" → Firestore → browser speech). **Do not copy its code.** Our approach is deliberately different: local object-level event tracking, not cloud frame captioning. | Credit as inspiration in the README |

The GitHub topic page `object-detection-and-tracking` is mostly generic YOLO + SORT demos; Visiona is the only one there with an object-memory + voice architecture worth borrowing. Don't spend more time browsing.

---

## 4. Architecture

```
iPhone camera ──(Continuity Camera / DroidCam)──► Frame grabber thread (latest frame only)
                                                        │
                                ┌───────────────────────┼─────────────────────────┐
                                ▼                       ▼                         ▼
                        YOLO-World detector      MediaPipe Hands           MediaPipe Pose
                                │                       │                         │
                                ▼                       │                         │
                     Identity (embedding gallery)       │                         │
                                └──────────┬────────────┘                         │
                                           ▼                                      ▼
                                 Event engine (per-item state machine) ◄──  Person tracker
                                           │                                (door / search sense)
                                           ▼
                                SQLite memory store  +  clip ring buffer
                                           │
           ┌───────────────┬───────────────┼────────────────┬────────────────────┐
           ▼               ▼               ▼                ▼                    ▼
     Answer engine    Voice loop      FastAPI + WS     Proactive rules     Photon bridge
   (Chalk Router LLM  (whisper in,   (memory frame,    (door check,        (texts, text-back,
    + templates)       `say` out)     dashboard)        search sense)       voice call)
```

Everything runs in **one Python process** with threads/asyncio, except possibly the Photon bridge (TypeScript, see Phase 9).

### Repo layout

```
lastseen/
  __main__.py            # starts everything; reads config.yaml
  config.py              # loads/validates config.yaml (pydantic)
  capture/
    camera.py            # frame grabber thread, latest-frame buffer, replay-from-video mode
    ringbuffer.py        # last ~6 s of downscaled frames for clips
  vision/
    detector.py          # YOLO-World wrapper
    identity.py          # embedding gallery: enroll + match (adapted from Visiona)
    hands.py             # MediaPipe HandLandmarker → hand boxes
    pose.py              # MediaPipe PoseLandmarker → person box, standing/sitting
  engine/
    states.py            # ItemState enum + transitions
    tracker.py           # per-item state machine, debouncing
    zones.py             # zones.json load, point-in-polygon, zone types
    events.py            # event objects, writes to store, publishes to bus
  memory/
    store.py             # SQLite (items, events, clips)
    clips.py             # write snapshot.jpg + clip.mp4 for an event; 24h cleanup
  brain/
    intents.py           # regex + LLM intent parsing
    answer.py            # deterministic answer builder + templates
    llm.py               # OpenAI-compatible client pointed at Chalk AI Router
  voice/
    listen.py            # mic → VAD → faster-whisper → find-intent spotting
    speak.py             # macOS `say` / Piper, non-blocking queue, mutes mic while speaking
  proactive/
    door_check.py
    search_sense.py
  server/
    app.py               # FastAPI, WebSocket bus, MJPEG stream, REST
    static/frame.html    # memory frame page
    static/dashboard.html# judge/caregiver dashboard
  integrations/
    photon_bridge/       # small TS (or Python) service, see Phase 9
    chalk_eval.py
  tools/
    draw_zones.py        # click-to-draw zone editor
    enroll.py            # CLI enrollment helper
    record_scenario.py   # record eval clips
    run_eval.py          # Chalk eval harness
config.yaml
zones.json
data/                    # gitignored: lastseen.db, clips/, gallery/
eval/scenarios/          # recorded eval videos + ground truth
THIRD_PARTY_NOTICES.md
NOTES.md
```

---

## 5. Setup

- macOS on Apple silicon, Python 3.11, `uv` for packages. Node 20+ only if the Photon bridge is TypeScript.
- Torch device: `mps` on Apple silicon, else `cuda`, else `cpu`. Detect once in `config.py`.

```bash
uv venv && source .venv/bin/activate
uv pip install ultralytics supervision mediapipe opencv-python faster-whisper \
  sounddevice webrtcvad fastapi "uvicorn[standard]" pydantic pyyaml shapely \
  openai open_clip_torch numpy
```

Model files to download in Phase 0 (store in `models/`, gitignored):
- `yolov8s-worldv2.pt` (Ultralytics downloads automatically on first use)
- MediaPipe `hand_landmarker.task` and `pose_landmarker_lite.task` (from the MediaPipe model page)
- faster-whisper `small.en` (downloads on first use)

`.env` (gitignored): `CHALK_ROUTER_KEY`, `CHALK_ENV_ID`, `CHALK_API_HOST`, Photon credentials, `CAREGIVER_PHONE`.

### config.yaml (starting point)

```yaml
camera:
  source: 0            # Continuity Camera index varies; tools/list_cameras.py finds it
  width: 1280          # never feed YOLO a 4K frame; small objects vanish after its internal resize
  fps_target: 8
  replay_video: null   # path to an .mp4 to run the whole system on a recording

items:                 # what we track; synonyms help the answer engine
  - id: keys
    prompt: "keys"
    synonyms: [keys, keychain, car keys]
    critical: false
  - id: inhaler
    prompt: "inhaler"
    synonyms: [inhaler, puffer, asthma inhaler]
    critical: true
  - id: epipen
    prompt: "epipen auto-injector"
    synonyms: [epipen, epi pen, epinephrine]
    critical: true
  - id: glasses
    prompt: "glasses case"
    synonyms: [glasses, eyeglasses, glasses case]
    critical: false
  - id: pills
    prompt: "pill organizer"
    synonyms: [pills, pill box, medicine, pill organizer]
    critical: true

detector:
  conf: 0.15           # YOLO-World needs a low threshold; identity check filters false positives
  imgsz: 1280

engine:
  held_frames: 3       # hand overlaps item this many processed frames → HELD
  placed_frames: 6     # item stationary without hand this many frames → PLACED
  missing_frames: 10   # item unseen this many frames → decide HIDDEN / CARRIED_OUT
  move_px: 25          # min displacement to count as a move

features:
  voice: true
  memory_frame: true
  door_check: true
  search_sense: false  # turn on only after Phase 8 passes
  photon: true
  photon_voice_call: false
  chalk_llm: true      # false → template answers only

people:
  user_name: "Mom"
  caregiver_name: "Anna"
```

---

## 6. Data model (SQLite)

```sql
CREATE TABLE items (
  id TEXT PRIMARY KEY,           -- "inhaler"
  display_name TEXT,
  critical INTEGER DEFAULT 0,
  state TEXT,                    -- PLACED | HELD | HIDDEN | CARRIED_OUT | UNKNOWN
  zone TEXT,                     -- "nightstand", "bed", ...
  bbox TEXT,                     -- JSON [x1,y1,x2,y2] at last sighting
  confidence REAL,
  last_seen_ts REAL,
  last_event_id INTEGER
);

CREATE TABLE events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts REAL,
  item_id TEXT,
  kind TEXT,                     -- PICKED_UP | PLACED | HIDDEN | CARRIED_OUT | SEEN
  from_zone TEXT,
  to_zone TEXT,
  bbox TEXT,
  confidence REAL,
  snapshot_path TEXT,            -- annotated jpg
  clip_path TEXT                 -- 3 s mp4
);

CREATE TABLE asks (              -- every question + answer, for evals and the dashboard
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts REAL, source TEXT,          -- voice | photon | dashboard | eval
  question TEXT, item_id TEXT, answer TEXT, state TEXT, zone TEXT, latency_ms INTEGER
);
```

---

## 7. Build phases

Each phase lists **tasks**, then an **acceptance check** a human can run in under 2 minutes. Target hours assume a 36-hour hackathon.

### Phase 0 — Skeleton + camera (target: hour 2)

1. Create the repo layout, `config.py` with pydantic validation, `__main__.py`, logging to console + `data/logs/session-*.jsonl` (borrow Visiona's JSONL session-log idea).
2. `tools/list_cameras.py`: try `cv2.VideoCapture(i)` for i in 0..5, print resolution, save a test jpg for each. Continuity Camera's index changes between runs; never hardcode it silently.
3. `capture/camera.py`: background thread that reads frames, resizes to `camera.width`, and keeps **only the latest frame** (drop old ones; never build a queue that lags). Also supports `replay_video` (loop an mp4 at real speed). Expose `get_latest() -> (frame, ts)`.
4. `capture/ringbuffer.py`: store the last ~6 s of frames downscaled to 640 px wide, for clips.
5. FastAPI skeleton with `/health` and an MJPEG `/stream` endpoint that shows the latest frame.

**Accept:** open `http://localhost:8000/stream` and see the iPhone feed live with < 0.5 s lag. Replay mode plays a recorded mp4.

### Phase 1 — Detection (target: hour 4) — the make-or-break phase

1. `vision/detector.py`: YOLO-World wrapper.
   ```python
   from ultralytics import YOLOWorld
   model = YOLOWorld("yolov8s-worldv2.pt")
   model.set_classes([i.prompt for i in cfg.items])
   res = model.predict(frame, conf=cfg.detector.conf, imgsz=cfg.detector.imgsz,
                       device=cfg.device, verbose=False)[0]
   ```
   Return a list of `(item_id, bbox, conf)`. Map class index → item id from config order.
2. Run detection in its own thread at `fps_target`; publish results to an in-process bus.
3. Dashboard overlay: draw boxes + labels on `/stream` using `supervision` annotators.
4. `tools/detect_report.py`: run 60 s on the live feed, print per-item hit rate (% of frames detected) and mean confidence.
5. **If any demo item is detected in < 60% of frames**, try in this order: (a) move the camera closer/higher and use a bigger version of the item; (b) try alternate prompts ("blue inhaler", "keychain with keys"); (c) try `yolov8m-worldv2.pt`; (d) fine-tune: capture ~150 frames per item with `tools/record_scenario.py`, label in Roboflow, export YOLO format, `yolo train model=yolo11s.pt data=... epochs=40 imgsz=1280`, and switch `detector.py` to the fine-tuned weights behind a config flag. Ultralytics also offers YOLOE, which supports visual prompts; worth a 15-minute test if YOLO-World struggles.

**Accept:** with the mock room set up, every demo item shows a box in ≥ 60% of frames when visible and not held.

### Phase 2 — Identity + enrollment (target: hour 7)

Goal: tell *your* sunglasses from any sunglasses, and enroll a judge's object live in ~10 s.

1. `vision/identity.py`, adapted from Visiona's MobileNetV3 + cosine-similarity approach (MIT; add notice). Use OpenCLIP ViT-B/32 image embeddings or MobileNetV3; pick whichever is faster on our laptop.
2. Gallery: `data/gallery/<item_id>/*.npy`, 5–10 embeddings per item.
3. Enrollment flow (`POST /api/enroll {item_id, display_name, prompt}` + `tools/enroll.py`):
   - Dashboard shows a center target box. Person holds the object in it for 2 s.
   - Capture 8 crops (center box, plus a YOLO-World box if found), embed, save.
   - If the item is new, add it to `items` at runtime and call `model.set_classes` again.
4. Matching: each detection crop → embedding → best cosine match among galleries of that class; accept if ≥ threshold (start 0.75, tune). Unmatched detections are ignored for tracking.

**Accept:** enroll a teammate's sunglasses; a different pair of sunglasses in view is not labeled as theirs.

### Phase 3 — Hands + event engine (target: hour 12) — the core

1. `vision/hands.py`: MediaPipe Tasks `HandLandmarker` (VIDEO mode, `num_hands=2`). Convert landmarks to a padded hand bbox (pad 20%).
2. `engine/zones.py` + `tools/draw_zones.py`: click polygons on a frozen frame, name them, set a **type**:
   - `surface` (nightstand, tray, desk), `cover` (bed with blanket, drawer, bag), `exit` (the door), `privacy` (blacked out before any processing).
   Save to `zones.json`. Point-in-polygon with `shapely` (or `supervision.PolygonZone`). An item's zone = the zone containing its bbox bottom-center.
3. `engine/tracker.py`: one state machine per enrolled item. Process at the detection rate.

   **States:** `UNKNOWN`, `PLACED`, `HELD`, `HIDDEN`, `CARRIED_OUT`.

   **Signals per tick:** `seen` (identity-matched detection), `bbox`, `hand_overlap` (IoU between item bbox and any hand bbox > 0.05, or item center inside hand bbox), `last_hand_zone`.

   **Transitions (with debouncing from config):**
   - `* → HELD`: `hand_overlap` for `held_frames` consecutive ticks. Emit `PICKED_UP` with `from_zone`.
   - `HELD → PLACED`: item seen, no hand overlap, bbox center moved < 5 px for `placed_frames` ticks. Emit `PLACED` with `to_zone`, snapshot + clip.
   - `HELD → HIDDEN`: item unseen for `missing_frames` ticks **and** the last hand position was inside a `cover` zone, and the hand then left without the item visible in it. Emit `HIDDEN` with `to_zone` = that cover zone.
   - `HELD → CARRIED_OUT`: item unseen for `missing_frames` ticks **and** the last hand position was inside an `exit` zone or at the frame edge. Emit `CARRIED_OUT`.
   - `PLACED → PLACED (moved)`: rare (pushed without visible hand): bbox moved > `move_px` while still seen → emit `PLACED` with new zone.
   - `PLACED → HIDDEN`: item unseen for `missing_frames` while it was inside a `cover` zone and a hand was nearby (blanket pulled over it).
   - `HIDDEN/CARRIED_OUT/UNKNOWN → PLACED`: seen again, stationary → emit `PLACED` (or `SEEN` if same zone).
   - Never transition on a single frame. Keep an `uncertain` flag when the evidence was weak (low conf, short occlusion); the answer engine says "probably".
4. `memory/clips.py`: on `PLACED`, `HIDDEN`, `CARRIED_OUT`: write `snapshot.jpg` (full frame, item bbox circled, zone label) and `clip.mp4` (ring-buffer frames from ~2.5 s before to ~0.5 s after the event; H.264 via `cv2.VideoWriter` with `avc1`, fall back to `mp4v`). A background job deletes clips older than 24 h.
5. Write every event to SQLite and publish it on the bus.

**Accept (scripted, record it once and keep it as an eval scenario):**
- keys from desk to tray → one `PICKED_UP`, one `PLACED zone=tray`, snapshot circles the keys.
- inhaler slid under the blanket → `HIDDEN zone=bed`.
- keys carried out through the door zone → `CARRIED_OUT`.
- No phantom events while someone just walks around for 30 s.

### Phase 4 — Answer engine (target: hour 15)

1. `brain/intents.py`: fast regex first, LLM second.
   - Find: `where('s| is| are| did I put)? (my |the |her |his )?(?P<item>...)`, "I can't find my X", "have you seen the X".
   - Held/time: "when did I last have X", "did I take my pills / open my pill organizer today".
   - Resolve `item` via synonyms in config; fuzzy-match (rapidfuzz) if no exact hit.
2. `brain/answer.py`: **deterministic** facts from the store, rendered with templates:
   - PLACED: "Your {item} is on the {zone}. You put it there at {time}."
   - HELD: "You're holding it right now."
   - HIDDEN: "I last saw your {item} going under the {zone} at {time}. It's probably still there."
   - CARRIED_OUT: "You picked up your {item} at {time} and took it out of the room."
   - UNKNOWN: "I haven't seen your {item} since {time}." / "I haven't seen it today."
   - `uncertain` → prefix "I think".
   Return `{text, item_id, state, zone, snapshot_path, clip_path}`.
3. `brain/llm.py`: OpenAI-compatible client pointed at **Chalk's AI Router** (see Phase 10 for details). Used for (a) parsing questions regex missed, via a single tool `get_item_status(item_id)`, and (b) optionally rewording the template answer to sound warm and short. Hard timeout 2.5 s → fall back to the template text.
4. `POST /api/ask {question, source}` → answer JSON; logs to `asks`.

**Accept:** `curl` five phrasings for three items; all return the correct state/zone; unplugging the network still returns template answers.

### Phase 5 — Voice (target: hour 18)

1. `voice/listen.py`: `sounddevice` mic stream (pre-warm it at startup like Visiona does), `webrtcvad` to cut utterances, `faster-whisper small.en` (`compute_type="int8"`) to transcribe. Only act if the transcript matches a find/time intent (no wake word). Discard all other audio immediately; never store it.
2. `voice/speak.py`: queue → macOS `say -v Samantha -r 165 "<text>"` in a subprocess (or Piper TTS). **Pause the listener while speaking** so the system doesn't hear itself.
3. On an answer: speak it, and publish `show_answer` on the bus for the memory frame.

**Accept:** standing 2 m from the laptop, say "where are my keys?" in a normal voice; the spoken answer starts within 3 s.

### Phase 6 — Memory frame + dashboard (target: hour 20) → FULL DEMO LOOP

1. `server/app.py`: WebSocket `/ws` broadcasting bus events (`event`, `show_answer`, `alert`, `item_update`). Serve `data/clips` read-only.
2. `static/frame.html` (the wall display, iPhone 2 / iPad):
   - Idle: big calm clock + date. Dark background, huge type.
   - On `show_answer`: full-screen snapshot with the item circled, item name in very large text, the answer sentence, and the clip looping muted. Return to idle after 60 s.
   - On `alert` (door check): red border, large text "Your inhaler is still on the bed."
   - Reconnect the WebSocket automatically. Add a manifest so it can be added to the home screen; use iOS Guided Access to keep it open.
3. `static/dashboard.html` (judges + caregiver view on the laptop screen): live MJPEG with boxes, zones, and hands drawn; item list with state chips; event timeline with thumbnails; a text box to ask questions (backup if voice fails).
4. Both phones load `http://<laptop-LAN-IP>:8000/...`. **Venue Wi-Fi often blocks device-to-device traffic: put the laptop and phones on one phone's hotspot.**

**Accept — the Hour 20 demo loop:** enroll an object → place it → ask out loud → spoken answer → memory frame shows the circled spot + clip. Record a backup video of this loop now.

### Phase 7 — Door check (target: hour 24)

1. `vision/pose.py`: MediaPipe `PoseLandmarker` (lite) at ~4 fps; person bbox + standing/sitting (hip vs knee height).
2. `proactive/door_check.py`: when the person's feet (ankle landmarks) enter the `exit` zone, check critical items. If any critical item is `PLACED` or `HIDDEN` in the room (not `HELD`, not `CARRIED_OUT`), then:
   - speak "Wait, your {item} is still on the {zone}."
   - publish `alert` to the frame.
   - trigger the Photon alert (Phase 9).
   - cooldown 2 minutes per item.

**Accept:** walk to the taped door without the inhaler → spoken warning + frame alert within 2 s; walk with it in hand → nothing.

### Phase 8 — Search sense (target: hour 30; first to cut)

`proactive/search_sense.py`: score over a 60 s window: standing (+1/s), visiting ≥ 3 distinct zones (+20), revisiting a zone (+10 each), hand entering a `cover` zone (+10), sitting resets to 0. Above a threshold, ask gently and **guess** one item: near the exit → keys; within 30 min of a configured med time → pills/inhaler; else the most recently handled item. Cooldown 5 min. Off by default; enable only if it fires reliably without false alarms.

### Phase 9 — Photon (target: hour 26; owner: Person D)

**First, at the Friday 4–5 PM workshop, confirm which Photon product "Photon 2.0" means.** Photon's docs have two versions:
- **Stable — Spectrum:** `spectrum-ts` (TypeScript), Spectrum webhooks, host `spectrum.photon.codes`, credentials = project ID + secret. Voice calls are added to a Spectrum iMessage line over SIP.
- **Beta — Photon platform:** API at `https://api.photon.codes/v1`, clients for TypeScript, **Python (`photonhq-api` on PyPI)**, Rust, Go; credentials start with `pho_`. Covers iMessage, email, and voice (voice agents via ElevenLabs/Retell/LiveKit/Twilio over SIP).

The challenge text (iMessage, SMS, RCS, WhatsApp, Telegram, email, **phone calls**) matches Beta best. **If Beta + Python:** write `integrations/photon.py` inside the main app. **If Spectrum:** write a small TypeScript service in `integrations/photon_bridge/` that talks to the Python app over HTTP.

Use Photon's documentation MCP server (`https://photon.codes/docs/mcp`, always pass the `version`) or `https://photon.codes/docs/llms.txt` to look up exact calls. Do not guess method names.

Behaviors to build:
1. **Outbound alert:** on door check or "critical item not seen for N hours" → text the caregiver: "{user}'s {item} is still on the {zone} and she just headed for the door." + the snapshot as an attachment.
2. **Text-back:** inbound message (webhook or event stream) → `POST /api/ask {source: "photon"}` → reply with the answer text + snapshot (+ clip if supported).
3. **Voice call (stretch, for Best Voice Agent):** on door check, place a call to the caregiver that speaks the alert; and/or accept inbound calls where a family member asks out loud, answered through the same `/api/ask`. Follow the voice cookbook for whichever version we're on.
4. Rate-limit outbound messages (iMessage deliverability: no bursts; max 1 alert per item per 10 min).
5. The webhook endpoint must be reachable from the internet: use the hosted/gateway mode Photon offers, or a tunnel (`cloudflared tunnel --url http://localhost:8000`). Verify webhook signatures per the docs.

**Accept:** a teammate's phone receives the door alert with a photo; texting back "where are her glasses?" returns the right answer within 10 s.

### Phase 10 — Chalk (target: hour 30; owner: Person B)

1. **AI Router:** Chalk's AI Router is an OpenAI-compatible gateway. In `brain/llm.py`:
   ```python
   from openai import OpenAI
   client = OpenAI(
       base_url=f"https://{CHALK_API_HOST}/v1/router",   # default host: api.chalk.ai
       api_key=CHALK_ROUTER_KEY,
       default_headers={"X-Chalk-Env-Id": CHALK_ENV_ID},
   )
   ```
   Confirm the exact host, key type, and allowed models with Chalk's docs (`docs.chalk.ai/docs/ai-router`) or their table at the event. Send only text: the question plus a compact JSON of item states and the last ~20 events. Never send images.
2. **Eval harness** (this is what wins the Chalk prize; judged on impact, use of data, and how it's evaluated):
   - `tools/record_scenario.py`: record 12 short videos in the mock room, each with `eval/scenarios/<name>/ground_truth.json`: `{question, expected_item, expected_state, expected_zone}`.
   - Required scenarios: keys → tray (PLACED), inhaler under blanket (HIDDEN), keys carried out (CARRIED_OUT), item held while asked (HELD), item never moved (PLACED), two similar items side by side (identity), item moved twice (latest zone wins), person walks around without touching anything (no events), plus 4 more variations (lighting, partial occlusion, fast pickup, judge-enrolled object).
   - `tools/run_eval.py`: run the full pipeline in replay mode on each video, ask the question through `/api/ask`, score state match, zone match, and "honest unknown" (answered UNKNOWN/HIDDEN rather than a wrong confident location). Output a table + headline, e.g. "state correct 11/12, zone correct 10/12, 0 confident wrong answers".
   - Check whether Chalk's eval tooling can ingest these results (their docs describe evals for LLM prompts). If yes, log the LLM phrasing eval there too; if not, show our table and route all LLM calls through the router so Chalk shows the traces.
3. Put the eval table in the README and on a slide. **Report real numbers only.**

### Phase 11 — Demo hardening (hours 30–36)

1. Feature freeze at hour 30. Only bug fixes after.
2. `/health` page: camera FPS, detector latency, last event time, mic status, Photon/Chalk reachability, all green/red.
3. Replay mode as a full fallback: if the live camera dies, run the system on the recorded demo video.
4. One command to reset state between demo runs: `python -m lastseen.tools.reset` (clears items' states/events, keeps galleries and zones).
5. Pre-recorded backup video of the full demo on the laptop desktop.
6. Rehearse the demo script in the plan doc ten times.

---

## 8. Cut list (in order, if behind schedule)

1. Search sense (Phase 8)
2. Clips (keep snapshots)
3. Photon voice call (keep texts; the Photon prize needs a live channel)
4. LLM rewording (keep templates; still route question parsing through Chalk)

**Never cut:** honest HIDDEN / CARRIED_OUT answers, the memory frame, the door check, Photon texts.

---

## 9. Known pitfalls

- **Continuity Camera index** changes between runs and sometimes pauses when the phone locks. Keep the phone plugged in, auto-lock off, and run `tools/list_cameras.py` before every demo.
- **Feed YOLO ~1280 px**, not 4K: small objects disappear after the model's internal resize.
- **Low YOLO-World confidence is normal.** Use `conf≈0.15` and let the identity check reject false positives.
- **MediaPipe Tasks** needs the `.task` model files; legacy `mp.solutions.hands` also works if Tasks gives trouble.
- **`say` blocks** if called directly; always run it in a subprocess from a queue, and pause the mic while it speaks.
- **Venue Wi-Fi** client isolation breaks phone ↔ laptop WebSockets; use a hotspot.
- **iMessage spam filtering:** don't blast test messages to many numbers; test with 1–2 teammates.
- **Threads + SQLite:** one writer thread, or `check_same_thread=False` with a lock.

---

## 10. README requirements (judges read it)

- What it does in 3 sentences; architecture diagram; how to run.
- **Where Photon is used** and **where Chalk is used** (explicit sections; sponsors check).
- Eval results table (real numbers).
- Privacy: video never leaves the laptop; what does leave.
- **Credits:** reCall (inspiration, Hack the North), Visiona (MIT, embedding re-ID and voice capture adapted), Ultralytics, Supervision, MediaPipe, faster-whisper. Full license texts in `THIRD_PARTY_NOTICES.md`.

---

## 11. Reference links

- Visiona (MIT): https://github.com/paavansirivardhan123/Visiona
- reCall (inspiration only, no license): https://github.com/darryltanzil/reCall
- Ultralytics YOLO-World: https://docs.ultralytics.com/models/yolo-world/
- Supervision: https://supervision.roboflow.com/
- MediaPipe hand landmarker: https://ai.google.dev/edge/mediapipe/solutions/vision/hand_landmarker
- MediaPipe pose landmarker: https://ai.google.dev/edge/mediapipe/solutions/vision/pose_landmarker
- faster-whisper: https://github.com/SYSTRAN/faster-whisper
- Photon docs index: https://photon.codes/docs/llms.txt (MCP server: https://photon.codes/docs/mcp)
- Chalk AI Router: https://docs.chalk.ai/docs/ai-router
- Chalk for AI engineers (prompts/evals): https://docs.chalk.ai/docs/chalk-for-ai-engineers
