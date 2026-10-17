# Last Seen — AirPods Full-Loop Milestone (Spec)

Date: 2026-10-16 · Status: draft for review
Companion docs: `CLAUDE.md` (build rules, architecture, phases), `Last Seen — HackHarvard 2026 Project Plan.pdf` (pitch, demo, sponsors).
Where this spec and `CLAUDE.md` disagree, this spec wins for this milestone only, and the difference is called out.

---

## 1. Intent

Prove the real Last Seen pipeline end to end on **one object, an AirPods case**, using the **real camera setup** (iPhone high in a corner), so that the actual demo items (inhaler, keys, EpiPen, pill organizer) can be added afterwards by config and enrollment only, with no structural code changes.

The AirPods case is a **dev stand-in**. It will not be in the judge demo. It was picked because it is the hardest kind of item for this setup: small, white, glossy, featureless, and easy to confuse with other white things. If the pipeline handles it, the larger demo items will be easier.

### Why now

The team has a working single-file prototype (`lastseen_demo.py`, run via `run_demo.sh`) built on Oct 14. It tracks the AirPods case from a laptop webcam using YOLO-World + CSRT + CLIP re-ID and answers by voice. Running it showed four problems this milestone must fix:

1. **Lost it / locked onto the wrong object.** It drifted to other white things or never picked the case back up after it left view.
2. **Too slow / laggy.** Low FPS on the Mac, with boxes trailing the object, because detection, CLIP, CSRT and drawing all run in one loop.
3. **Locking on was fiddly.** SPACE auto-lock often grabbed the wrong thing, so the user had to draw a box with R.
4. **"Last seen" was taken while the case was still in a hand** (see `answers/answer_220024.jpg`). The prototype has no idea of picked-up versus put-down, so the remembered spot can be mid-air in someone's hand.

### Timeline and rules

- HackHarvard starts this weekend. **This spec and the implementation plan are prep. Code gets written once the event clock starts**, in line with the usual hackathon rule. The existing prototype counts as prior work and should be declared if the rules ask.
- This milestone is the CLAUDE.md "Hour 20 demo loop" (Phases 0–6), done on the AirPods case first.

---

## 2. Goals, non-goals, anti-goals

### Goals (done means all of these)

**The full loop on the AirPods case, with the corner iPhone:**

1. **Enroll** the AirPods case by saying or clicking "enroll AirPods", then **picking it up and putting it down** in view (§4.3).
2. **Move it.** Pick it up from one zone and put it down in another. The system logs `PICKED_UP` then `PLACED zone=<new zone>` in SQLite within 2 s of the hand letting go.
3. **Ask by voice** from about 2 m away: "Where are my AirPods?" No wake word.
4. **Spoken answer** starts within 3 s: "Your AirPods are on the desk. You put them there at 3:42." The phrasing comes from Chalk's AI Router, with the template text as fallback if the router is slow or down.
5. **The memory frame** (a browser page on a second phone or iPad) goes full screen within 2 s of the question: a snapshot with the case circled, the item name, the answer sentence, and a ~3 s clip of the put-down playing on a loop.
6. **The dashboard** (browser, laptop) shows the live corner feed with item box, hand boxes and zones drawn, the item's state chip, the event timeline with thumbnails, and a text box for typed questions.
7. **The four Oct 14 problems are fixed** (§1). Acceptance tests are in §7.
8. **Leaving the camera's view** (rescoped 2026-10-16 by the user: no doors, no ankles; leaving the view is the largest scale, §4.11): if the person holding an item walks out of the frame through any edge, the item becomes `CARRIED_OUT` right away. Asking gives "You picked up your AirPods at 3:42 and took them out of view."
9. **Four demo items, configured ahead of time** (user's call, updated 2026-10-16): `airpods`, `glasses`, `playing_cards`, `water_bottle`. Nothing else is ever named (§4.12).
10. **Touch-to-track** (user's call, 2026-10-16, §4.13): no explicit enroll step. The system follows hands continuously; when a hand touches one of the four items and lets go, it works out which item it was, locks onto it, and follows it from then on. One snapshot is taken at the moment the hand lets go.

### Non-goals (not in this milestone)

- **Photon** (texts, text-back, voice call): comes right after this milestone (Phase 9).
- **Chalk eval harness**: not built now. The AirPods test recordings (§7) may later become eval scenarios, but no harness work is in scope.
- **Search sense** (Phase 8).
- **Door check, door zones, spoken "you left X behind" warnings:** dropped by the user (2026-10-16). Nothing in this build knows about doors.
- **HIDDEN** is not an acceptance criterion for this milestone. The state machine must have room for it (§4.4), and it may be built if time allows. (**CARRIED_OUT is in scope** through "holder left the view", §4.11.)
- **Touch-to-track for any object** (auto-tracking and naming whatever a hand picks up): *designed for* in this milestone, built later (§5).
- Multiple tracked items at once. The code must support N items. Only one needs to work for this milestone.
- A local OpenCV window. The browser dashboard is the only dev view.
- Multiple people handling objects at once. Assume **one person in view handles objects at a time**.

### Anti-goals (would be a failure even if it "works")

- **Remembering the case in a hand as its location.** The location is only ever written when the case is set down and stable.
- **A confident wrong answer.** If evidence is weak, say "I think…" or say when it was last seen. Never name a zone the case isn't in. (CLAUDE.md rule 4: location and state come from the database and state machine, never from the LLM.)
- **Any image leaving the laptop.** Only text goes to Chalk. Frames are never written to disk except event snapshots and clips in `data/clips/`, which are deleted after 24 h (CLAUDE.md rule 5).
- **AirPods-specific code paths.** Nothing outside `config.yaml` and the gallery may know it's an AirPods case. Swapping to the inhaler must be a config + enrollment change.
- **A UI that waits on the model.** Video on the dashboard must stay smooth, with lag under 0.5 s, even when detection is slow.

---

## 3. Decisions already made (by the user)

| Topic | Decision |
|---|---|
| Codebase | **Build the `lastseen/` package** laid out in CLAUDE.md §4. Port the working parts of `lastseen_demo.py` into it, then **retire the demo file**. Delete it, or move it to `legacy/`, once the package's loop runs. |
| Camera | **iPhone mounted high in a corner** via Continuity Camera, looking down at a small mock room. Answers name **zones** ("on the desk"), not directions relative to the person. The prototype's `describe_location` (behind you / to your left) is dropped. |
| Enrollment | **Pick up + put down.** Trigger enrollment (voice or dashboard button), then pick the item up and set it down in view. The hand shows which object it is. |
| Detection fallback | **Hand-led tracking.** The detector is not required to find the case cold from the corner. The pipeline follows what the hand carried and confirms the put-down spot with CLIP + template + change detection. |
| Detection risk | **Untested.** Whether YOLO-World sees the case from the corner is unknown, so the first build step is a detection check (§6, step 1). |
| Done means | **Full loop on AirPods** (Phases 0–6). |
| Sponsors in milestone | **Chalk AI Router in the loop** (question parsing + answer phrasing, template fallback). **Photon after.** |
| Dev view | **Browser dashboard only.** |
| People | **One person handles objects at a time.** |
| Future object naming | **Local only.** When unknown objects are named later, CLIP zero-shot runs on the laptop against a local vocabulary. No crop goes to a cloud vision model. |
| Code timing | Spec now, code at the event. |
| Builders | **The team builds in parallel.** §4.10 fixes the interfaces up front so the work can split. |
| Hardware | **Base M1/M2 Mac, 8–16 GB.** The speed budget (§4.5) assumes this from the start. |
| Leaving | **Only "person left the camera's view".** No doors, door lines, ankles or door warnings. Person tracking uses **Ultralytics** `yolo26n` (person class) with its built-in ByteTrack; **Supervision** handles detections and drawing. |
| Demo items | **Four items, configured ahead of time:** AirPods, glasses, playing cards, water bottle (§4.12). No laptop. Untouched or unknown objects (a mug, a pen) are ignored. |
| Locking on | **Touch-to-track** (§4.13): a hand touches an item and lets go → identify which of the four → lock on. **One snapshot when the hand lets go**, never continuous capture. |
| Manual enroll | *Claude's call:* the existing enroll command and click-to-enroll stay as a hidden backup for the demo. |

### Calls made by Claude while writing this (check these)

- **Before the event clock starts:** hardware and testing only. That means mounting the iPhone, building the mock room, `uv` environment and model downloads, the step-1 detection/hands check (a throwaway script, not product code), and recording the §7 test clips. The plan PDF treats "research, testing, and buying parts beforehand" as normally fine. Product code in `lastseen/` waits for the clock.
- **No schema change.** `uncertain` is derived from `events.confidence` (below `engine.uncertain_conf`, default 0.6, means uncertain), so it survives restarts with no new column. Per-item extras (optional `prompt`, origin config/enrolled, template, negative gallery) go in sidecar files under `data/gallery/<item_id>/` (`meta.json`, `pos_*.npy`, `neg.npy`, `template.png`). CLAUDE.md rule 7 is respected.
- **Every tracked item needs a gallery.** A config-only item with no enrollment is shown as "not enrolled yet" and never tracked by detector alone; this keeps the no-confident-wrong-answer guarantee. Demo items (inhaler, keys, EpiPen, pills) get enrolled once during setup. Galleries persist, and `tools/reset` keeps them.

---

## 4. How it works (design)

### 4.1 Process and threads

One Python process (`python -m lastseen`), following CLAUDE.md §4:

- **Capture thread** (`capture/camera.py`): reads Continuity Camera and keeps **only the latest frame**, resized to 1280 px wide. Ported from the prototype's `LatestFrame`. Also supports `camera.replay_video` (loop an mp4 at real speed) for repeatable tests.
- **Ring buffer** (`capture/ringbuffer.py`): the last ~6 s of frames at 640 px wide, for clips.
- **Vision thread**: runs at `fps_target` (8). Per tick: hands, then detector + identity (with a budget, §4.5), then the tracker. It **never blocks the capture thread or the server**.
- **Server** (`server/app.py`, FastAPI + uvicorn): MJPEG `/stream` with the latest *annotated* frame (overlays come from the last vision result, so drawing never waits on inference), WebSocket `/ws`, REST, static pages.
- **Voice thread**: listen, then a speak queue (§4.7).
- **Bus**: a simple in-process pub/sub that the vision thread, answer engine and voice publish to, and the WebSocket broadcasts from.
- Every background loop catches, logs and continues (CLAUDE.md rule 8).

### 4.2 Signals per vision tick

- **Hands:** MediaPipe Tasks `HandLandmarker` (VIDEO mode, `num_hands=2`), giving hand boxes padded by 20%.
- **Detector proposals:** YOLO-World with the item's `prompt` plus extra prompts from config (measured in §8a: `["airpods case", "white earbuds case", "small white plastic case", "earbuds", "cell phone", "remote", "white box"]`). Very low conf (**0.001**). The detector only proposes boxes; identity decides. Boxes bigger than 25% of the frame are dropped.
- **Change proposals (new):** a slowly updated background model of the scene. Regions that changed and stayed changed after a hand left are candidate "something was put here" boxes. This is the main signal for hand-led tracking (§4.4), because it doesn't depend on the detector knowing what an AirPods case looks like from above.
- **Template proposals:** multi-scale template match against the enrolled crop. Ported from the prototype. Run only when searching, not every tick.
- **Identity:** CLIP ViT-B/32 embeddings (already downloaded at `models/clip/ViT-B-32.pt`) scored against the item's **positive gallery** and a **negative gallery** of background patches and look-alikes from the same scene. Ported from the prototype's `Embedder` + `_negatives`. A candidate counts as the item only if `pos ≥ sim_thresh` **and** `pos − neg ≥ margin`. Reacquiring after loss needs a stricter threshold than continuing to follow. Both rules come from the prototype and are the fix for "locked onto the wrong white thing".

### 4.3 Enrollment: pick up + put down

1. The user triggers enrollment: dashboard button "Enroll item" with name + optional prompt, or `POST /api/enroll {item_id, display_name, prompt?}`. Voice ("enroll my AirPods") is a nice-to-have. The system says "OK, pick it up and put it down where I can see it."
2. The system snapshots the background, then waits for a hand to enter, stay for a moment, and leave.
3. When the hand leaves, it diffs the scene against the pre-pickup background **around where the hand was last**:
   - If something **appeared** (the item was brought in and set down), that blob is the item.
   - If something **disappeared and reappeared elsewhere** (picked up from one spot, put down at another), the reappeared blob is the item, and the vacated spot confirms it.
   - If a YOLO-World box overlaps the blob, use the union. The detector refines the box but is not required.
4. Over the next ~`placed_frames` ticks, while the item stays still, it captures ~8 crops (with slight jitter/padding), embeds them, and saves them to `data/gallery/<item_id>/*.npy`. It also builds the negative gallery from the rest of the scene and stores the grayscale template.
5. The item is created (or updated) in `items` with state `PLACED`, its zone, and bbox. A `PLACED` event with snapshot + clip is logged, and the system confirms by voice: "Got it. I'll remember your AirPods."
6. If no clear single blob is found (nothing changed, or several things changed), it says so ("I couldn't tell which thing you put down — try again a bit more in the open") rather than guessing. As a backup, the dashboard lets the user **click the object on the live feed** to enroll it, the browser version of the prototype's R key.

This replaces the prototype's SPACE auto-lock and R box-drawing (problem 3). The same "hand left, something appeared" mechanism is what touch-to-track will reuse (§5).

### 4.4 The tracker: hand-led state machine

One state machine per item (`engine/tracker.py`), with the states from CLAUDE.md: `UNKNOWN, PLACED, HELD, HIDDEN, CARRIED_OUT`. The milestone needs `PLACED ↔ HELD` to be solid. The other transitions exist with the CLAUDE.md rules but are not acceptance-tested.

**While PLACED (the common case: cheap and sticky):**
- Expect the item at its stored bbox. Each tick, verify **only at that location** with CLIP (and template). This is cheap and avoids scanning the whole frame for look-alikes.
- If verification fails briefly (a person walks in front), keep `PLACED`. It doesn't flip on one frame.
- `PLACED → HELD`: a hand overlaps the item bbox (IoU > 0.05 or item center inside the hand box) for `held_frames` ticks, **and** after that the item is no longer verified at its old spot, or its box moves with the hand. This emits `PICKED_UP` with `from_zone`. A hand brushing past without taking it should not count.

**While HELD (the case is usually hidden by fingers):**
- The item's live position is **the holding hand's box**. Don't try to detect a small white case inside a fist.
- **Never write a location while HELD.** This fixes problem 4.
- The dashboard overlay shows "held" on the hand.

**HELD → PLACED (the put-down, which is what we remember):**
- The hand leaves a region, and a **change proposal** appears near the hand's last position that wasn't there before the pickup. That candidate passes identity (pos/neg margin) and stays still (< 5 px movement) for `placed_frames` ticks.
- This emits `PLACED` with `to_zone` (the zone containing the bbox's bottom-center), writes the snapshot + clip, and re-anchors the location prior.
- Detector and template proposals near the hand's last position also count as candidates. Global detector proposals far from the hand do **not** trigger a put-down unless identity is very strong. This is the second fix for wrong-object lock (problem 1).

**HELD for too long with nothing put down:** after `missing_frames` with no hand, use the CLAUDE.md `HIDDEN` / `CARRIED_OUT` rules (last hand position in a `cover` or `exit` zone, or at the frame edge). If neither applies, fall back to `UNKNOWN` and keep `last_seen` from the last `PLACED` event, never from the hand.

**Reacquire (UNKNOWN / HIDDEN → PLACED):** run a periodic global search (detector + template + change proposals, at a lower rate). Require the stricter reacquire thresholds and `placed_frames` of stillness. Emit `PLACED`, or `SEEN` if it's in the same zone as before.

**Uncertainty:** set an `uncertain` flag when the put-down was decided on weak evidence (low margin, short stillness, change blob but weak CLIP match). The answer engine then says "I think…".

**Online learning (ported):** when a verification is very strong, occasionally add a new view to the gallery, capped at ~12 embeddings. This handles the lid open or the case flipped.

### 4.5 Speed budget (problem 2)

- Capture, vision and server are separate threads. MJPEG serves the newest frame with the newest overlays, so it is never blocked on inference.
- Inference device is `mps` when available, else `cpu` (detected once in `config.py`).
- **Base M1/M2 budget, planned from the start:** a "vision tick" is hands + tracker update and targets ≥ 6/s. YOLO-World runs **every 3rd tick** by default (`detector.every_n: 3`), and the tracker uses the newest detector result in between. CLIP runs on ≤ 6 crops per detector tick, but on only 1 crop (the stored location) in steady `PLACED`. If hands can't keep up, run them every 2nd tick while no hand was seen in the last second, and every tick once a hand is present. Measure on the real Mac in step 1 and set the defaults from the numbers.
- Per tick: hands every tick. YOLO-World at `imgsz` from config (**1280**: at 960 a case ~20 px wide stops being proposed; §8a). CLIP on **at most ~6 candidates**, batched.
- In steady `PLACED` state, CLIP runs only on the stored location (one crop), and the global detector can drop to every Nth tick.
- Drop CSRT from the main loop, or keep it only as an optional short-gap bridge behind a flag. In the hand-led design the hand box does the frame-to-frame following, and CSRT at 1280 px was a large part of the prototype's lag.
- `/health` shows the camera FPS, vision tick rate, and per-stage latency, so lag is measurable, not guessed.

### 4.6 Zones

- `tools/draw_zones.py`: freeze a frame from the corner camera, click polygons, name them, set a type (`surface`, `cover`, `exit`, `privacy`), and save to `zones.json`.
- Suggested dev mock room: `desk` (surface), `tray` (surface), `bed` (cover, with a blanket), plus any `privacy` areas. No exit/door zone.
- An item's zone is the zone containing its bbox bottom-center. If it's in no zone, the answer uses a fallback: "on the floor near the desk" (nearest zone), or "in the room" if nothing is near.
- `privacy` zones are blacked out before any processing.

### 4.7 Answer engine and voice

- **Intents** (`brain/intents.py`): regex first ("where is/are my X", "I can't find my X", "have you seen the X"), with item resolution through config synonyms plus fuzzy match. For the AirPods case: `[airpods, air pods, earbuds, earpods, headphones, airpods case]`. The prototype's regex is a starting point.
- **Answer** (`brain/answer.py`): deterministic facts from the store, rendered with the CLAUDE.md templates (PLACED / HELD / HIDDEN / CARRIED_OUT / UNKNOWN, with "I think" when uncertain).
- **Chalk AI Router** (`brain/llm.py`): OpenAI-compatible client pointed at Chalk, used for (a) parsing questions the regex missed, via one tool `get_item_status(item_id)`, and (b) rewording the template answer to be short and warm. Text only: the question plus compact JSON of item states and recent events. **Hard timeout 2.5 s, then the template.** Behind `features.chalk_llm`. Exact host, key type and model come from Chalk's docs or their team at the event (CLAUDE.md rule 6).
- **`POST /api/ask {question, source}`** returns `{text, item_id, state, zone, snapshot_path, clip_path, uncertain}` and logs to `asks`.
- **Listen** (`voice/listen.py`): pre-warmed `sounddevice` stream, VAD, then faster-whisper. The prototype used `base.en`, which is already downloaded. CLAUDE.md suggests `small.en`; use `base.en` unless accuracy needs more. Act only on find intents and discard all other audio immediately.
- **Speak** (`voice/speak.py`): a queue feeding macOS `say` in a subprocess. **The listener is paused while speaking.** The prototype didn't do this, so it could hear itself.
- An answer publishes `show_answer` on the bus.

### 4.8 Memory frame and dashboard

- **`/frame`** (wall display): idle shows a big clock + date, dark. On `show_answer`: full-screen snapshot with the case circled, item name in very large text, the answer sentence, and the clip looping muted. It returns to idle after 60 s and reconnects the WebSocket automatically. The prototype's `render_answer` (spotlight dimming + circle) is the visual reference for snapshots.
- **`/dashboard`**: live MJPEG with item box (green = verified, amber = last seen, hand = held), hand boxes and zone outlines. Also an item list with state chips, an event timeline with thumbnails, an ask box, an "Enroll item" button, and click-to-enroll on the feed.
- Phones load `http://<laptop-LAN-IP>:8000/frame`. Use a phone hotspot if the venue Wi-Fi isolates clients.

### 4.9 Storage

Use the CLAUDE.md §6 SQLite schema unchanged (`items`, `events`, `asks`), with one writer (or a lock). Snapshots and clips go in `data/clips/` with 24 h cleanup. The gallery lives in `data/gallery/<item_id>/` together with the sidecar `meta.json`, template and negatives (see "Calls made by Claude" in §3). All of `data/` and `models/` is gitignored.

### 4.10 Interfaces for parallel work (agree in hour 1, then don't change them without telling the team)

Owners follow the plan PDF's roles: **A** vision (tracker, enrollment, zones), **B** brain + voice + Chalk, **C** memory frame + camera/room + clips, **D** dashboard + pitch (Photon later).

**Bus messages** (in-process pub/sub, the same JSON broadcast on `/ws`; every message has `type` and `ts`):

```json
{"type":"event","ts":0,"event":{"id":1,"item_id":"airpods","kind":"PLACED","from_zone":"tray","to_zone":"desk","bbox":[x1,y1,x2,y2],"confidence":0.84,"uncertain":false,"snapshot_url":"/clips/…jpg","clip_url":"/clips/…mp4"}}
{"type":"item_update","ts":0,"item":{"id":"airpods","display_name":"AirPods","state":"HELD","zone":null,"bbox":[…],"confidence":0.9,"last_seen_ts":0,"enrolled":true}}
{"type":"show_answer","ts":0,"answer":{ /* same shape as /api/ask response */ }}
{"type":"overlay","ts":0,"items":[{"id":"airpods","bbox":[…],"style":"verified|last_seen|held"}],"hands":[[…]]}
{"type":"enroll_status","ts":0,"item_id":"airpods","stage":"waiting_pickup|waiting_putdown|done|failed","message":"…"}
{"type":"person","ts":0,"track_id":3,"kind":"entered_view|left_view"}
```

**`POST /api/ask`** `{question, source: "voice"|"dashboard"|"photon"|"eval"}` → `{text, item_id, state, zone, uncertain, snapshot_url, clip_url, ts_placed, latency_ms}`. If the item isn't recognised: `item_id: null` and a helpful `text`.

**`POST /api/enroll`** `{item_id, display_name, prompt?}` → `{ok}`; progress then arrives as `enroll_status` messages. **`POST /api/enroll/click`** `{item_id, display_name, x, y}` is the click-to-enroll backup.

**Tracker → store contract:** only the tracker writes `items` and `events`, through `memory/store.py` (`upsert_item`, `add_event`), which returns the event id and publishes `event`/`item_update`. Everyone else only reads. `brain/answer.py` reads through `store.get_item(item_id)` and `store.recent_events(n)`.

**Stubs so nobody waits:** day one ships a `FakeTracker` behind `features.fake_tracker`. It replays a scripted sequence of events (AirPods tray → desk) with real-looking snapshots, so B can build answers/voice/Chalk, C the frame and D the dashboard before A's tracker exists.

### 4.11 People and leaving the view

**Person tracking** (`vision/people.py`):
- Ultralytics **`yolo26n.pt`** (person class only, auto-downloads) with `model.track(frame, persist=True, tracker="bytetrack.yaml", classes=[0])`. Each person gets a stable `track_id` and a box. No pose model, no keypoints.
- It runs every 2nd vision tick (~4/s), which is enough for walking speed.
- `sv.Detections.from_ultralytics(result)` carries the boxes and `tracker_id`s, which are used for overlays.

**Left the view:** a track counts as having left when it was last seen with its box within **3% of a frame edge** and has then been missing for **1 s**. (ByteTrack keeps a lost track for ~30 frames, so this rule decides, not the tracker's own timeout.) A person who stands still in the middle of the room and is briefly missed did *not* leave.

**Who holds what:** a hand box belongs to the person whose box contains it (or the nearest one). A `HELD` item records `holder_track_id`.

**Carried out** (in `engine/tracker.py`): when the holder's track leaves the view while the item is `HELD` by that track, the tracker emits `CARRIED_OUT` (`to_zone` = null) immediately. The answer template is "You picked up your {item} at {time} and took {it|them} out of view." Fallback when no person was tracked: the hand was last seen within 5% of a frame edge, and the item is unseen for `missing_frames`. Coming back and putting it down is the normal `HELD → PLACED`. Seeing it again without a hand is the normal reacquire. A person leaving *without* the item changes nothing.

### 4.12 The four demo items

Configured in `config.yaml` ahead of time, `critical: false` for all four:

| id | display name | detector prompt + extras (proposals only) | spoken synonyms |
|---|---|---|---|
| `airpods` | AirPods | airpods case; white earbuds case, small white plastic case, earbuds | airpods, air pods, earbuds, earpods, headphones, airpods case |
| `glasses` | glasses | glasses; eyeglasses, sunglasses, glasses case | glasses, eyeglasses, sunglasses, specs, my glasses |
| `water_bottle` | water bottle | water bottle; bottle, reusable bottle, drink bottle | water bottle, bottle, my bottle, water |
| `playing_cards` | playing cards | playing cards; deck of cards, card box, small box | playing cards, cards, deck of cards, deck, card deck |

The generic proposal prompts from §8a ("cell phone", "remote", "white box") are always added. Items are locked onto by touch (§4.13); manual enroll remains as a backup. `tools/reset` keeps the galleries. (The sleeping mask was dropped and the water bottle added on 2026-10-16; the order in config.yaml is airpods, glasses, playing_cards, water_bottle.)

---

### 4.13 Touch-to-track (added 2026-10-16)

**What the user sees:** they touch one of the four items and let go of it; within ~2 s it has a green box with its name on the live view, and asking "where are my AirPods?" works. No enroll command. Touching anything else does nothing.

**Hand episodes** (in the vision loop, per hand, using the hand boxes already computed every tick):
- An episode starts when a hand appears; at that moment take a ChangeDetector snapshot (the "before" picture of the scene). Remember where the hand first appeared.
- The episode ends when the hand has been absent for 3 consecutive ticks after being present ≥ 0.5 s (same debounce as enrollment). Shorter presences are flickers and are discarded.
- At the end: look for changed regions vs the episode's snapshot near where the hand was last seen (within near_hand_px), plus detector boxes there. The item is the region **nearest the hand's last position**; a region near where the hand *first* appeared is the vacated spot (the item was lifted from there) and is not the item. If nothing changed near the release point (the hand only brushed something), the episode ends with nothing.
- Episodes are only for items that are not locked yet. Once an item is locked, its own tracker handles pick-ups and put-downs exactly as today (§4.4), so an episode whose release point is on an already-tracked item's box is ignored.

**Which item is it** (closed list of the four, never anything else):
- Score the candidate crop against each untracked item with CLIP **text** matching: the image embedding versus the text embeddings of the item's prompt and extra prompts (prompt-ensemble average), plus a set of "other" prompts ("a hand", "a table", "a phone", "a cup", "a pen", "background"). Turn the scores into probabilities over items + other.
- YOLO-World labels overlapping the crop (IoU > 0.3) for an item add evidence (boost that item's score).
- Accept the top item only if it beats "other" **and** leads the runner-up by a clear margin (*Claude's call:* start at probability ≥ 0.45 and a lead ≥ 0.15; tune live). Otherwise log what it saw and do nothing — never a confident guess.

**Locking on:** build the item's appearance gallery from this put-down (the same finalize step manual enrollment uses: 8 jittered crops, negatives, template; meta origin `"auto"`), create its tracker restored as PLACED at the box, and write **one** PLACED event with **one snapshot** taken at that moment. The item row's display name comes from config.

**Snapshots and clips:** files are only ever written at events (put-down, hidden, carried out), never continuously; the frame ring buffer stays in memory. *Claude's call:* the 3 s clip at an event stays (it feeds the memory frame) but goes behind `features.clips` so it can be turned off; the snapshot is always written.

**Mistakes:** if it locks onto the wrong item, the manual enroll command re-learns that item (overwrites its gallery). A `POST /api/forget {item_id}` endpoint removes an item's gallery and tracker so touch-to-track can learn it again. *Claude's call.*

**Settled details (from the builder check; Claude's calls unless noted):**
- *Picked up and carried off without a put-down:* the user asked that touching an item locks onto it, so a lift also counts. At the start of each hand episode keep a copy of the colour frame. If the episode ends with no new region near the release point but a **vacated** region near where the hand first touched (the item was lifted away), identify the item from that region in the saved "before" frame. Lock it as HELD (its gallery comes from the before-frame crop). Its tracker then follows it as usual: put down → PLACED, holder leaves view → CARRIED_OUT.
- *Several hands / items at once:* one episode per tracked hand. Episodes whose release point (or vacated spot) overlaps a locked item's box or held hand are ignored. At most one new lock per tick; the rest wait for the next tick.
- *Manual enroll running:* touch-to-track episodes are suppressed while a manual enroll session is active. Each episode takes its own ChangeDetector snapshot and drops it when it ends.
- *CLIP text matching:* uses the text encoder already inside the loaded ViT-B/32 model (`encode_text`). No new model or dependency. Item text embeddings are computed once at startup.
- *Data model:* origin `"auto"` lives only in `data/gallery/<item>/meta.json`. No database change.
- *What counts as "changed":* the existing ChangeDetector rules (difference threshold ~25, region 0.02%–5% of the frame). A brush that leaves nothing changed near the release point locks nothing.

**Not in scope:** naming objects outside the four; two items released by one hand at the same moment (the nearest region wins); locking onto items nobody touched.

## 5. Designed for, built later: touch-to-track any object

Not built in this milestone, but the code must not block it:

- **The tracker is keyed by `item_id`, not by a detector class.** A detector `prompt` is optional per item. An item can exist with only a gallery (enrolled by pick-up/put-down) and no prompt at all.
- **Enrollment and tracking share one "hand left, something appeared here" routine** (§4.3 / §4.4). Touch-to-track becomes: on *any* unclaimed put-down blob, create a provisional item automatically, instead of only after an explicit "enroll".
- **Naming is local only.** When built, a provisional item's crop is scored with CLIP zero-shot against a local household vocabulary (a few hundred words). The top guess becomes its display name ("probably a water bottle"), and a later voice or text correction fixes the label. No image leaves the laptop.
- Storing a guessed label or the item's origin (config / enrolled / auto) would **change the data model**. Per CLAUDE.md rule 7, that needs the team's OK when touch-to-track is built. It is not done now.
- Items added at runtime must not require a restart. If an item has a prompt, call `set_classes` again.

---

## 6. Build order for this milestone

These are the CLAUDE.md phases, re-cut for the AirPods milestone. Step 1 happens before the clock starts. At the clock: step 2 plus the §4.10 interfaces and `FakeTracker` come first (one person, ~1–2 h). After that, steps 3–4 (A), 5–6 (B) and 7 (C + D) run in parallel against the stubs. Each step ends with its check and a commit (`git init` first; the folder isn't a repo yet). `python -m lastseen` must run after every commit.

1. **Detection check (first, ~30 min).** Mount the iPhone in the corner over the mock room. With a throwaway script (it can reuse prototype code), measure for the case lying still on desk, tray and bed: the YOLO-World hit rate with the four prompts at `imgsz` 960 and 1280, and the case's pixel size. Write the numbers in `NOTES.md`. This tells us how much weight the detector gets versus change proposals. It **does not block** the build, because the design is hand-led either way.
2. **Skeleton + camera** (Phase 0): package layout, pydantic `config.py`, JSONL session logs, `tools/list_cameras.py`, capture thread (ported), ring buffer, FastAPI `/health` + `/stream`, replay mode.
3. **Detection + identity** (Phases 1–2): detector wrapper, CLIP identity with pos/neg galleries (ported), dashboard overlay with `supervision` annotators.
4. **Hands + zones + tracker + enrollment** (Phase 3 + §4.3): hands, `draw_zones.py`, the change-proposal background model, the hand-led state machine, pick-up/put-down enrollment, snapshots + clips, SQLite events. Record the §7 test clips here and keep them for replay.
5. **Answer engine + Chalk** (Phase 4): intents, templates, `/api/ask`, Chalk router client with timeout fallback.
6. **Voice** (Phase 5): port the listener, add the speak queue with mic pause.
7. **Memory frame + dashboard** (Phase 6): WebSocket bus, `/frame`, `/dashboard`.
7b. **People + leaving the view** (§4.11; Track A once the tracker works): person tracking, the holder link, and `CARRIED_OUT` when the holder leaves the view.
8. Retire `lastseen_demo.py` and `run_demo.sh` (or move them to `legacy/`). Update `THIRD_PARTY_NOTICES.md` and `NOTES.md`.

---

## 7. Acceptance tests

Run these with the corner iPhone and the mock room (desk, tray, bed + blanket). Each scripted test is also recorded once as an mp4 so it can be re-run in replay mode.

| # | Test | Pass when |
|---|---|---|
| A1 | **Enroll** | Trigger enroll, pick the case up from the desk and put it on the tray. A gallery is saved, the item is `PLACED zone=tray`, and the voice confirms. Takes ≤ 15 s. No box drawing needed. |
| A2 | **Move** | Pick the case up from the tray and put it on the desk. Exactly one `PICKED_UP from=tray` and one `PLACED to=desk`. `PLACED` is logged within 2 s of the hand leaving. The snapshot circles the case on the desk, not a hand. |
| A3 | **Held is not a location** | Pick the case up and hold it in the air for 10 s while asking "where are my AirPods?" The answer is "You're holding it right now." No `PLACED` event while it's in the hand. *(Fixes problem 4.)* |
| A4 | **Look-alikes** | Put 2–3 other small white objects in view (a pill bottle, a white charger, a white mug) and do A2 again. The case is never reported at a look-alike's spot. Tracking 2 minutes with no handling: zero phantom events. *(Fixes problem 1.)* |
| A5 | **Occlusion** | A person stands in front of the case on the desk for 5 s, then moves. It stays `PLACED zone=desk` throughout, with no events. |
| A6 | **Speed** | Dashboard stream lag < 0.5 s. Vision tick ≥ 6/s on the team's Mac. `/health` shows both. *(Fixes problem 2.)* |
| A7 | **Voice → frame** | From ~2 m, say "Where are my AirPods?" The spoken answer starts ≤ 3 s, and `/frame` on the second device shows the circled snapshot + looping clip ≤ 2 s after the question. |
| A8 | **Phrasings** | `curl /api/ask` with 5 phrasings ("where are my airpods", "I can't find my earbuds", "have you seen my AirPods case", "where did I put my headphones", "airpods?"). All return the right state and zone. |
| A9 | **Offline** | With Wi-Fi off, A8 still returns correct template answers within 1 s. |
| A11 | **Carried out of view** | Pick up the case and walk out of the frame holding it. `CARRIED_OUT` is logged within 2 s. Asking gives "You picked up your AirPods at {time} and took them out of view." Walk back in and put it on the tray: `PLACED zone=tray`. |
| A12 | **No false carried-out** | Walk around inside the view for 30 s, holding the case and then without it, including past the edges of the room without leaving the frame: no `CARRIED_OUT`. Leave the view *without* the case: nothing changes. |
| A13 | **Touch-to-track** | With no galleries saved, pick up the AirPods case and put it down. Within ~2 s it shows a green "AirPods" box and one PLACED event with one snapshot is logged; no enroll command was sent. Repeat for the glasses, playing cards and water bottle. |
| A14 | **Ignores other things** | Touch and move a mug or a pen: nothing is locked, nothing is logged except a diagnostic line. Brush the AirPods case without lifting it: no lock. |
| A10 | **Swap test** | Lock onto a second of the four items by touch (e.g. glasses) with pick-up/put-down. Moving both items logs correct events for each. No code change needed. |

---

## 8. Risks

| Risk | Mitigation |
|---|---|
| The case is ~20–40 px from the corner; detector and CLIP are weak at that size | Hand-led + change proposals carry the put-down. Pad crops for context (the prototype used 15%). Keep the mock room small and the camera as low as still looks natural. |
| The background model reacts to lighting changes or a shifting blanket | Update it only when no hand or person is in the area. Require a change blob near the hand's last position **and** an identity match. |
| MediaPipe misses hands from a high, steep angle | Check in step 1 alongside detection. If it's weak, also use the pose landmarker's wrist points as a hand proxy. |
| Two hands, or a hand that hovers without taking anything | Need sustained overlap plus "gone from old spot / moved with hand" before declaring `HELD`. |
| Continuity Camera index changes or pauses | `tools/list_cameras.py` before every run. Keep the phone plugged in with auto-lock off. Replay mode as fallback. |
| A person walks behind furniture in the middle of the room and the tracker loses them | "Left the view" needs the last box near a frame edge, so mid-room misses never count. |
| Chalk access details unknown until the event | Template fallback works without it. `features.chalk_llm: false` switches it off. |

### 8a. Measured on 2026-10-16 (laptop webcam, prototype)

- YOLO-World scores the AirPods case at only **0.001–0.02** under AirPods-type prompts, even at 84 px. The old 0.02 cutoff threw it away, and a junk box (an elbow at the frame edge) won auto-lock. Prompts the model knows, like "cell phone" and "remote", score the case 10–100× higher, so they are used as proposal prompts.
- At `conf 0.001` and `imgsz 1280`, the case is still proposed at **~21 px** wide.
- CLIP gap (case vs best non-case box, same scene): +0.27 at 51 px, +0.11 at 34 px, **+0.06 at 21 px**. Non-case boxes score **−0.16 or lower**. At 15 px the case is no longer separable (−0.10). So identity gates mainly on the margin, with a low raw-similarity floor.
- Teaching the gallery blurry "far" versions of the crop made the gap *worse* (0.22 → 0.09), so it is not used.
- Auto-lock only inside a centre target, never on a box touching the frame edge.
- With these settings, the prototype locked on the first press 7/7 times, including the case at ~38 px from across the room. Cost: about 58 ms per frame on the M-series Mac (~17 fps).

---

## 9. Left to the builder

- How the background / change model works (running average, MOG2, or a per-zone reference image), as long as A2, A4 and A5 pass.
- Exact thresholds (`sim_thresh`, margins, frame counts). Start from the measured values in §8a (sim 0.70, margin 0.02 follow / 0.04 reacquire) and CLAUDE.md config, then tune on the recorded clips.
- YOLO-World `imgsz` and model size, from the step-1 numbers.
- Whether CSRT survives at all (§4.5).
- Dashboard and frame visual styling, within the CLAUDE.md descriptions.
- Whisper model size (`base.en` vs `small.en`).
