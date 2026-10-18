# Last Seen — Wearable Camera + "Are you looking for…?" (Spec)

> Local copy only (`~/Desktop/hackharvard0.1-local`, no git remote). Written 2026-10-17 from an interview with the user.
> Builds on `.plans/airpods-full-loop-spec.md` and `.plans/touch-to-track-plan.md`.

## 1. Intent

A judge said a wearable beats a wall camera. The iPhone now hangs on the user's chest in a Neewer magnetic POV neck mount and streams to the laptop over Continuity Camera. The camera moves with the person, so:

- There is no person to track: the wearer is never in the frame.
- There are no fixed zones: the background changes all the time.
- "Left the room" can't be detected anymore. The new proactive cue is: **an item you put down has been out of view for 30 s → "Are you looking for your AirPods?"**

30 s is for the demo. In real life it would be a few minutes, so it's a config value.

## 2. Goals, non-goals

### Goals (done means all of these)

1. `camera.mode: wearable` runs the whole loop on a moving camera, with no zones, no person tracking and no background-change detection.
2. An item becomes **tracked** when the user's hand touches it for ~0.5 s and then lets go (it's seen without a hand on it).
3. Several items can be tracked at once (the design works for all 5; only AirPods is switched on in this build).
4. A tracked item that was **put down** and then stays out of view for 30 s makes the laptop ask, **"Are you looking for your AirPods?"**, then listen 8 s for yes/no.
5. If 2+ items come due within 10 s of each other, it asks once: **"Are you looking for something?"** → yes → **"OK, what item are you looking for?"**
6. "Yes" → **"You put your AirPods down 2 minutes ago. I put a photo of where on the screen."** and the laptop dashboard shows the last-seen snapshot full size.
7. Dashboard button **"I know where it is"** per item silences the question until the item is seen again. The snapshot is kept.
8. Everything sits behind flags. `camera.mode: fixed` brings back the current behavior unchanged.

### Non-goals (this build)

- The other 4 items. They are in config but `enabled: false` until the teammate's galleries land (§4.9).
- The mobile "I know where it is" page. It uses the same API later.
- Location words ("on the desk"). Location is the snapshot only.
- Photon, door check, search sense.
- Any image leaving the laptop (privacy invariant unchanged).

### Anti-goals

- Asking about all items every time the user turns around.
- Asking about an item that's in the user's hand below the frame.
- Asking while the camera feed is down.
- A confident wrong answer about an item that was never touched.

## 3. Decisions made by the user

| Topic | Decision |
|---|---|
| Video link | Continuity Camera (wireless), same as now |
| Items | water bottle, wallet, keys, glasses, AirPods. Playing cards removed. **Only AirPods enabled now.** |
| Recognition | Teammate hard-codes the 5 items as **gallery files** in `data/gallery/<item>/` (format the current identity code reads). |
| Touch rule | Hand on item ~0.5 s, then let go → tracked |
| Item carried out of frame in hand | Don't ask; it's "with you" |
| Single item due | "Are you looking for your {item}?" then wait for yes/no |
| 2+ items due within 10 s | "Are you looking for something?" → yes → "OK, what item are you looking for?" → named item untracked → "Sorry, I did not see you interact with your {item}." |
| Reply to yes | Time + "I put a photo of where on the screen." (snapshot only, no place words) |
| Where the snapshot shows | Laptop dashboard |
| Audio | Laptop mic + speaker |
| Reply window | 8 s. Loose yes/no words. Silence = not silenced; timer restarts and it may ask again after another 30 s unseen. |
| "No" / dashboard button | Silenced until the item is **seen again** |
| "Seen again" | 3 identity matches within 1 s |
| Snapshot | Best (sharpest, most confident) frame from the last ~5 s before it vanished |
| Camera drop | Pause all timers while frames are stale (>1 s); dashboard shows "camera lost" |
| Static-camera parts | Behind a flag (`camera.mode`), code kept |
| Demo | Wear camera → pick up AirPods → put on table → walk off / turn away ~30 s → laptop asks → "yes" → dashboard shows snapshot |

### Calls made by Claude (check these)

- **No database change.** States stay `PLACED | HELD | HIDDEN | CARRIED_OUT | UNKNOWN`. "Out of view" isn't a state: it's derived from `last_seen_ts` on a `PLACED` item. "With you" is stored as `CARRIED_OUT` (held when it left view). The best-frame snapshot is written as a `SEEN` event when the item goes out of view.
- **The group rule is checked at once, with no waiting.** When item A comes due, any other eligible item that's unseen for ≥ `ask_after_s − group_window_s` (i.e. due within the next 10 s) joins a group question. The single-item question is never delayed 10 s.
- **A find question during the reply window** ("where are my AirPods?") is answered through the normal path and closes the window.
- **"Placed" on a moving camera** means seen with no hand on it for `placed_frames` ticks. It's no longer "box stationary in pixels", since the camera moves.

## 4. Design

### 4.1 Mode switch

`camera.mode: wearable | fixed` (default `wearable` in this copy). In wearable mode, the vision loop skips:
- `ChangeDetector.update` / blobs, `TouchWatcher` (background-diff touch-to-track)
- `vision/people.py` and `LeaveWatcher`
- zones (`zone_at` returns None; privacy mask off; no zone drawing)

Hands (MediaPipe), the detector (YOLO-World proposals), the embedder and the identity galleries stay.

### 4.2 Per-tick signals (wearable)

- `hands`: hand boxes (MediaPipe), every tick.
- `cands`: detector boxes for enabled items' prompts plus generic prompts → CLIP embedding → best gallery match per item (`accepts()` with the existing thresholds). This is a **global search every tick**: no hand anchors or "near last position", because positions mean nothing between frames of a moving camera.
- `fresh`: the frame timestamp is < `stale_frame_s` old and differs from the previous one (Continuity freeze check: identical frame hash 10 ticks in a row counts as stale).
- `sharpness` per frame: variance of the Laplacian on the item crop. Used only for best-frame selection.

Detector cadence: `detector.every_n` drops to 1 in wearable mode if the measured tick time allows ≥ 5 ticks/s. Otherwise 2. The builder measures and records it in §8.

### 4.3 Wearable item tracker (`engine/wear_tracker.py`, new)

One per enabled item that has a gallery. States (internal) → stored state:

| internal | meaning | stored state |
|---|---|---|
| `UNTRACKED` | never touched this session | `UNKNOWN` (no row update) |
| `HELD` | hand on it ≥ `touch_s` | `HELD` |
| `PLACED_VISIBLE` | put down, currently seen | `PLACED` |
| `PLACED_GONE` | put down, now out of view | `PLACED` (last_seen_ts frozen) |
| `WITH_YOU` | left view while held | `CARRIED_OUT` |

Transitions:
- `UNTRACKED/PLACED_* → HELD`: matched box overlaps a hand (IoU > 0.05 or item center inside hand box) for ≥ `touch_s` (0.5 s). Emit `PICKED_UP`.
- `HELD → PLACED_VISIBLE`: matched with no hand overlap for `placed_frames` ticks. Emit `PLACED` + snapshot. **This is the moment the item becomes tracked** the first time.
- `HELD → WITH_YOU`: unseen for `missing_frames` ticks while held. Emit `CARRIED_OUT` (template: "You picked up your {item} at {time} and had {it|them} with you.")
- `WITH_YOU → PLACED_VISIBLE`: seen again (seen-again rule) without a hand → emit `PLACED` (put down while out of view).
- `PLACED_VISIBLE → PLACED_GONE`: unseen for `missing_frames` fresh ticks. Write the best frame of the last `best_frame_window_s` as a `SEEN` event snapshot (circle the item box from that frame). Start the unseen timer.
- `PLACED_GONE → PLACED_VISIBLE`: seen-again rule (`seen_again_hits` = 3 matches within `seen_again_window_s` = 1.0 s). Resets the timer and clears any silence. No new event (avoids event spam while looking around). The last-seen snapshot is updated at the next `→ PLACED_GONE`.
- Never touched → stays `UNTRACKED` no matter how often it's seen.

Best-frame buffer: per item, a deque of `(ts, score, frame_ref, box)` for the last 5 s while visible. score = match sim × normalized sharpness × box-area factor (penalize tiny boxes and boxes touching the frame edge). Store full frames only for the current top-1 (memory bound); downscale to 1280 px.

### 4.4 Unseen timer and asker (`proactive/lost_sight.py`, new)

Per tracked item: `unseen_s` (only counts while `fresh`), `silenced: bool`, `asked_at`.

**Eligible** = state `PLACED_GONE`, not silenced, no dialog open.

Every tick (vision thread publishes item states on the bus; the asker runs on its own thread at 4 Hz):
1. Add elapsed time to `unseen_s` of `PLACED_GONE` items only while `fresh`.
2. If any eligible item has `unseen_s ≥ ask_after_s` (30):
   - group = eligible items with `unseen_s ≥ ask_after_s − group_window_s` (20).
   - 1 item → single question. 2+ → group question.
3. Only one dialog at a time. Nothing is asked while the speaker is talking or another answer was spoken < 3 s ago.

### 4.5 Dialog (`proactive/dialog.py`, new)

The listener's `on_text` checks first whether a dialog window is open. If so, the transcript goes to the dialog; otherwise it goes to the existing route.

**Single:** say "Are you looking for your {display}?" → window `reply_window_s` (8 s), starting when speech ends.
- yes (`yes|yeah|yep|yup|i am|sure|please|where`) → say "You put your {display} down {ago}. I put a photo of where on the screen." + bus `show_answer` with the snapshot + log to `asks` (source `proactive`).
- no (`no|nope|i know|i'm fine|i'm good|not really`) → silence until seen again.
- find question for any item → normal answer, close window.
- timeout / unclear → not silenced; `unseen_s` resets to 0 (asks again after another 30 s unseen).

**Group:** say "Are you looking for something?" → 8 s.
- yes → say "OK, what item are you looking for?" → 8 s for an item name (synonyms of **all 5 config items**, enabled or not, + fuzzy match):
  - tracked item → the same answer as single-yes (or the `WITH_YOU` / `HELD` template).
  - known item, never touched/tracked → "Sorry, I did not see you interact with your {display}."
  - no item recognized → "Sorry, I didn't catch that." and close.
- no → silence every item in the group until seen again.
- timeout → reset `unseen_s` of all group items.

`{ago}`: "just now" (<60 s), "N minutes ago", "at 2:14" (>60 min).

### 4.6 API + dashboard

- `POST /api/dismiss {item_id}` → silence until seen again; closes an open dialog about that item (group: removes it from the group). Snapshot kept. Same thread rules as other requests.
- Bus `item_update` gains `unseen_s`, `silenced`, `asking` (ephemeral, not in DB).
- Dashboard item card: state chip, "out of view 0:23", "Asking…" badge, button **I know where it is** (enabled when tracked and out of view or asking), thumbnail of the last-seen snapshot.
- `show_answer` on the laptop dashboard: a full-size snapshot overlay with the answer text, closed by a click or after 60 s.
- Status bar: "camera lost" when frames are stale.
- Zone editor / zone drawing hidden in wearable mode.

### 4.7 Config

```yaml
camera:
  mode: wearable          # wearable | fixed

items:                    # order: airpods, water_bottle, wallet, keys, glasses
  - id: airpods      ... enabled: true
  - id: water_bottle ... enabled: false
  - id: wallet       display_name: wallet, prompt: "wallet", extra_prompts: [leather wallet, billfold, card holder],
                     synonyms: [wallet, my wallet, billfold, purse], enabled: false
  - id: keys         display_name: keys, prompt: "keys", extra_prompts: [keychain, car keys, key ring],
                     synonyms: [keys, key, keychain, car keys, my keys], enabled: false
  - id: glasses      ... enabled: false

wearable:
  ask_after_s: 30
  group_window_s: 10
  reply_window_s: 8
  touch_s: 0.5
  seen_again_hits: 3
  seen_again_window_s: 1.0
  stale_frame_s: 1.0
  best_frame_window_s: 5

features:
  lost_sight_ask: true
  touch_to_track: false   # the background-diff version; fixed mode only
  people_tracking: false
```

`ItemCfg.enabled: bool = True`. Disabled items aren't detected or tracked, but their synonyms still resolve in questions (so the group flow can say "I did not see you interact with…").

### 4.8 What stays the same

Answer engine templates, `asks` logging, Chalk router (text only), speaker muting the mic, SQLite schema, clips behind `features.clips`, `tools/reset` (also clears unseen timers/silences).

### 4.9 Seam for the teammate

The galleries are dropped into `data/gallery/<item_id>/` in the existing format (`Gallery` in `vision/identity.py`). An item with `enabled: true` but no gallery logs a warning at startup and stays off. Turning an item on = gallery present + `enabled: true`. No code change.

## 5. Build order

1. Config: `camera.mode`, `wearable` block, `ItemCfg.enabled`, 5 items (cards out), flags. Tests.
2. Vision loop wearable path: skip change/people/zones; global per-tick matching; stale-frame check. Tests with fakes.
3. `WearTracker` state machine + best-frame buffer + `SEEN` snapshot on going out of view. Tests.
4. `LostSightAsker` timers + group rule. Tests with a fake clock.
5. Dialog + listener hook + yes/no/item parsing. Tests with scripted transcripts.
6. `/api/dismiss`, bus fields, dashboard card/button/overlay/camera-lost.
7. Live run on the neck mount with AirPods; tune; record a backup video.

Each step: tests pass (`.venv/bin/python -m pytest -q`), `python -m lastseen` starts, local commit (no remote).

## 6. Acceptance tests

Live, wearing the neck mount, AirPods only:

1. Touch AirPods ≥ 0.5 s and put them down → dashboard shows "AirPods · PLACED" within 2 s.
2. Look away for 30 s → laptop says "Are you looking for your AirPods?" within 31–33 s of them leaving view.
3. Say "yes" → spoken time sentence + dashboard shows a sharp snapshot with the AirPods circled.
4. Repeat; say "no" → no more questions until the AirPods are back in view, then 30 s away again → it asks again.
5. Repeat; click **I know where it is** → silenced the same way; the snapshot is still visible on the card.
6. Pick AirPods up and keep them in hand below the frame for 60 s → no question. "Where are my AirPods?" → "…had them with you."
7. AirPods seen on the table but never touched → no tracking, no question.
8. Unplug/lock the phone for 45 s → no question; "camera lost" shown; timer resumes after.
9. Silence after the question → no answer; it asks again ~30 s later.

Unit (fakes, no models): group rule (two items due 5 s apart → one generic question; 15 s apart → two single questions); group flow naming a disabled item → "did not see you interact"; seen-again needs 3 hits in 1 s (1 hit doesn't reset); stale frames don't count; `camera.mode: fixed` suite still passes unchanged.

## 7. Risks

- **Motion blur while walking** → missed matches → item flips to "gone" while still in view. Mitigation: `missing_frames` counts fresh ticks; seen-again rule; tune `missing_frames` live.
- **Continuity Camera range/drops** on a moving phone → stale-frame pause; keep the demo within a few meters of the Mac.
- **Neck-mount angle**: the camera points down/forward; hands are often at the bottom edge. Check that MediaPipe still finds hands when only fingers are visible.
- **AirPods case is small and white**: matching at a distance may fail; the best-frame score favors bigger boxes.
- **Laptop mic at distance** for "yes": the demo stays within ~2 m of the laptop at the moment of the question.
- **Per-tick global CLIP matching cost**: `MAX_BOXES` cap stays; measure.

## 8. Measured (fill in during build)

- Tick rate wearable mode: …
- Detector every_n chosen: …
- AirPods match rate while walking / standing: …
