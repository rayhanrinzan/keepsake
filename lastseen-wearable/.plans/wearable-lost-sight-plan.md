# Wearable Camera + "Are you looking for…?" Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run Last Seen on a phone worn on the chest. It tracks an item after a touch-and-release, and when a put-down item stays out of view for 30 s it asks "Are you looking for your AirPods?" and answers yes/no by voice, with the snapshot on the laptop dashboard.

**Architecture:** `camera.mode: wearable` swaps the vision loop's tracker step for a new pure `WearTracker` per enabled item (global gallery matching every detector tick, no zones/people/change detection). The loop publishes a read-only per-item status snapshot. A new `LostSightAsker` (own 4 Hz thread) reads it, runs the 30 s timers, the group rule and the yes/no dialog, and speaks through the existing `Speaker`. Answers come from `AnswerEngine` with wearable templates. `camera.mode: fixed` keeps today's code path untouched.

**Tech Stack:** Python 3.12, existing `lastseen` package (CLIP gallery identity, YOLO-World proposals, MediaPipe hands, faster-whisper, macOS `say`), FastAPI, pytest.

**Spec:** `.plans/wearable-lost-sight-spec.md`

**Repo:** `/Users/romanstashkiv/Desktop/hackharvard0.1-local` only (no git remote; never add one, never push).

## Global Constraints

- Items in config.yaml, in this order: `airpods` (enabled), `water_bottle`, `wallet`, `keys`, `glasses` (all `enabled: false`). `playing_cards` removed. All `critical: false`.
- Wearable defaults: `ask_after_s: 30`, `group_window_s: 10`, `reply_window_s: 8`, `touch_s: 0.5`, `seen_again_hits: 3`, `seen_again_window_s: 1.0`, `stale_frame_s: 1.0`, `best_frame_window_s: 5`.
- Exact copy: "Are you looking for your {display}?", "Are you looking for something?", "OK, what item are you looking for?", "You put your {display} down {ago}. I put a photo of where on the screen.", "Sorry, I did not see you interact with your {display}.", "Sorry, I didn't catch that.", "You picked up your {display} at {time} and had {it} with you."
- `{ago}`: "just now" (< 60 s), "1 minute ago" / "N minutes ago" (< 60 min), else "at {fmt_time(ts)}".
- No SQLite schema change. Stored states stay `PLACED | HELD | HIDDEN | CARRIED_OUT | UNKNOWN`; event kinds stay as today (the going-out-of-view snapshot is a `SEEN` event).
- `camera.mode` defaults to `"fixed"` in `CameraCfg` (so existing tests are unchanged); config.yaml sets `wearable`. The whole existing suite must still pass.
- No images leave the laptop. No new dependency.
- Every background loop step is wrapped in try/except (log, continue). Tests never load CLIP, YOLO, MediaPipe or whisper.
- Test command: `.venv/bin/python -m pytest -q -W error`. Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. `git add` explicit paths only; never anything under `.superpowers/`.

## Review Focus

1. **Detector runs every 2nd tick:** ticks with no detector output must not count as "missing" or reset hits. Test in Task 2 (`test_not_looked_ticks_do_not_count_missing`).
2. **Continuity Camera freezes (same frame repeated) or stops:** the unseen timer must not advance and no question fires. Tests in Task 3 (`test_identical_frames_are_stale`) and Task 5 (`test_no_ask_when_not_fresh`).
3. **The user answers while the question is still being spoken:** the 8 s window opens only after speech ends, and audio heard while speaking is muted anyway. Test in Task 5 (`test_reply_window_starts_after_speech`).
4. **Restart with DB rows from an earlier run (PLACED):** wearable trackers start untracked, so no question fires for stale rows. Test in Task 3 (`test_wearable_starts_untracked`).
5. **"Yeah, I know where it is"** must count as no, not yes; dismissing one item of an open group question keeps the question for the rest. Tests in Task 5 (`test_parse_reply`, `test_dismiss_during_group`).

---

### Task 1: Config — mode, wearable block, item enable flag, five items

**Files:**
- Modify: `lastseen/config.py`, `config.yaml`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `CameraCfg.mode: Literal["wearable", "fixed"] = "fixed"`; `class WearableCfg(BaseModel)` with the eight fields and defaults from Global Constraints; `Config.wearable: WearableCfg`; `ItemCfg.enabled: bool = True`; `FeaturesCfg.lost_sight_ask: bool = True`; `Config.enabled_items() -> list[ItemCfg]` (items with `enabled`, config order).

- [ ] **Step 1: Write failing tests** in `tests/test_config.py`:
```python
def test_repo_config_is_wearable():
    cfg = load_config("config.yaml")
    assert cfg.camera.mode == "wearable"
    assert [i.id for i in cfg.items] == ["airpods", "water_bottle", "wallet", "keys", "glasses"]
    assert [i.id for i in cfg.enabled_items()] == ["airpods"]
    assert cfg.wearable.ask_after_s == 30 and cfg.wearable.group_window_s == 10
    assert cfg.wearable.reply_window_s == 8 and cfg.wearable.seen_again_hits == 3
    assert cfg.features.lost_sight_ask is True
    assert cfg.features.touch_to_track is False and cfg.features.people_tracking is False

def test_mode_defaults_to_fixed():
    assert Config(items=[ItemCfg(id="a", display_name="A")], device="cpu").camera.mode == "fixed"
```
Update the existing item-list assertion in this file to the new order.
- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/test_config.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.** config.py fields above. config.yaml: `camera.mode: wearable`; items per spec §4.7 (keep airpods/glasses/water_bottle entries as they are now, add `enabled`; wallet: prompt `wallet`, extra `[leather wallet, billfold, card holder]`, synonyms `[wallet, my wallet, billfold, purse]`; keys: prompt `keys`, extra `[keychain, car keys, key ring]`, synonyms `[keys, key, keychain, car keys, my keys]`); `wearable:` block; `features.touch_to_track: false`, `features.people_tracking: false`, `features.lost_sight_ask: true`.
- [ ] **Step 4: Run** the whole suite. Expected: PASS (fix any test that read the repo config.yaml and hard-coded `playing_cards`).
- [ ] **Step 5: Commit** `feat: wearable mode config, five demo items (AirPods enabled)`.

---

### Task 2: WearTracker, BestFrame, frame score (pure)

**Files:**
- Create: `lastseen/engine/wear_tracker.py`, `tests/test_wear_tracker.py`

**Interfaces:**
- Consumes: `Candidate`, `TrackerEvent`, `Box` from `lastseen/types.py`; `WearableCfg`, `EngineCfg`.
- Produces:
  - `@dataclass WearObs(ts: float, looked: bool, fresh: bool, hands: list[Box], cand: Candidate | None, accepted: bool, frame_wh: tuple[int, int])`. `looked` = the detector ran this tick; `cand` = the best-scoring candidate for this item (or None); `accepted` = it passed `Identity.accepts`.
  - `class WearTracker(item_id: str, engine_cfg: EngineCfg, wear_cfg: WearableCfg)` with:
    - `phase: Literal["UNTRACKED","HELD","PLACED_VISIBLE","PLACED_GONE","WITH_YOU"]` (starts `UNTRACKED`)
    - stored-row attributes used by `VisionLoop._upsert` / overlay: `state` (property: UNTRACKED→`UNKNOWN`, HELD→`HELD`, PLACED_*→`PLACED`, WITH_YOU→`CARRIED_OUT`), `zone = None`, `bbox: Box | None`, `live_box: Box | None`, `confidence: float`, `last_placed_ts: float | None`
    - `unseen_s: float`, `last_seen_ts: float | None`, `sightings: int` (incremented on each PLACED_GONE→PLACED_VISIBLE and WITH_YOU→PLACED_VISIBLE)
    - `step(obs: WearObs) -> list[TrackerEvent]`
  - `frame_score(sim: float, sharpness: float, box: Box, wh: tuple[int, int]) -> float`
  - `class BestFrame(window_s: float)` with `offer(ts, score, frame, box) -> None`, `best(now) -> tuple[np.ndarray, Box, float] | None`, `clear() -> None`.

Transition rules (pinned; `hand_on` = existing `_hand_on` rule: IoU > 0.05 or box center inside a hand box):
```
seen = obs.looked and obs.accepted
touch timer: while seen and hand_on(cand.box): touch_since kept, else reset; held when ts - touch_since >= touch_s
UNTRACKED/PLACED_VISIBLE/PLACED_GONE -> HELD on touch timer:   emit PICKED_UP(from_zone=None, bbox)
HELD -> PLACED_VISIBLE when seen and not hand_on for engine.placed_frames looked ticks: emit PLACED(bbox)
HELD -> WITH_YOU when not seen for engine.missing_frames looked ticks:                  emit CARRIED_OUT(to_zone=None)
PLACED_VISIBLE -> PLACED_GONE when not seen for engine.missing_frames looked ticks:     emit SEEN(bbox=last seen box); unseen_s = 0
PLACED_GONE / WITH_YOU -> PLACED_VISIBLE when seen-again (>= seen_again_hits seen ticks within seen_again_window_s)
    and not hand_on: sightings += 1, unseen_s = 0; WITH_YOU additionally emits PLACED(bbox); PLACED_GONE emits nothing
unseen timer: in PLACED_GONE, on fresh ticks unseen_s += min(ts - prev_ts, wear_cfg.stale_frame_s)
not-looked ticks: change no counters except the unseen timer and the touch timer's clock
```
`frame_score`: `sim * min(1, sharpness / 100) * min(1, area_frac / 0.01) * (0.5 if box within 2% of any frame edge else 1)`. `BestFrame` keeps one `(score, frame, box, ts)` per whole-second bucket (highest score wins), drops buckets older than `window_s`, and `best(now)` returns the highest-scoring kept entry (frame is the caller's copy; it's stored as given).

- [ ] **Step 1: Write failing tests** (helper `obs(ts, seen=True, hand=False, looked=True, fresh=True, box=B)` builds a WearObs):
```python
def test_touch_then_release_tracks():         # hand on 0.5 s -> PICKED_UP; 6 looked ticks without hand -> PLACED; phase PLACED_VISIBLE, state "PLACED"
def test_brief_touch_does_not_track():        # hand on 0.3 s then gone -> no events, phase UNTRACKED
def test_seen_but_never_touched_stays_untracked():  # 40 seen ticks, no hand -> []
def test_held_out_of_view_is_with_you():      # HELD, then 10 unseen looked ticks -> CARRIED_OUT, state "CARRIED_OUT", unseen_s stays 0
def test_placed_then_gone_emits_seen_and_counts():  # PLACED_VISIBLE, 10 unseen -> SEEN; 30 s of fresh ticks at 0.125 -> unseen_s ≈ 30.0
def test_not_looked_ticks_do_not_count_missing():   # PLACED_VISIBLE, alternate looked-unseen/not-looked for 18 ticks -> still PLACED_VISIBLE
def test_seen_again_needs_three_hits_in_window():   # PLACED_GONE: 1 hit -> still GONE, unseen_s not reset; 3 hits within 1 s -> VISIBLE, sightings == 1, unseen_s == 0
def test_stale_ticks_do_not_advance_timer():  # PLACED_GONE, 20 ticks fresh=False -> unseen_s unchanged
def test_gap_is_clamped():                    # PLACED_GONE, one fresh tick 10 s after the previous -> unseen_s grows by 1.0
def test_with_you_put_down_out_of_view():     # WITH_YOU, seen-again without hand -> PLACED event, PLACED_VISIBLE
def test_frame_score_prefers_big_central_sharp(): # same sim: central 60x60 sharp > edge-touching 60x60 > tiny 6x6
def test_best_frame_window():                 # offers at t=0..7 with scores, best(7.0) ignores entries older than 5 s, returns the max
```
- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/test_wear_tracker.py -q`. Expected: FAIL (module missing).
- [ ] **Step 3: Implement** `lastseen/engine/wear_tracker.py` per the rules above (module docstring states it's the wearable counterpart of `ItemTracker`).
- [ ] **Step 4: Run** the test file, then the suite. Expected: PASS.
- [ ] **Step 5: Commit** `feat: WearTracker state machine and best-frame buffer`.

---

### Task 3: VisionLoop wearable path

**Files:**
- Modify: `lastseen/engine/vision_loop.py`
- Test: `tests/test_vision_loop.py` (new `WearRig` next to `Rig`)

**Interfaces:**
- Consumes: Task 2's `WearTracker`, `WearObs`, `BestFrame`, `frame_score`; `Config.enabled_items()`, `cfg.camera.mode`.
- Produces:
  - `@dataclass WearStatus(item_id: str, display_name: str, phase: str, unseen_s: float, last_seen_ts: float | None, sightings: int)` in `lastseen/engine/wear_tracker.py`.
  - `VisionLoop.wear_status() -> tuple[list[WearStatus], bool]`: the snapshot published at the end of the last tick, plus `fresh` = last tick was fresh **and** it ran less than `wear_cfg.stale_frame_s` ago (monotonic). Safe to call from any thread (returns copies).
  - `VisionLoop.metrics["camera_lost"]: bool`.

Behaviour in `camera.mode == "wearable"`:
- `_init_items`: store rows for all config items as today; trackers (`WearTracker`) only for enabled items with a gallery (warn `"%s enabled but has no gallery; not tracking it"` otherwise). Every wearable tracker starts UNTRACKED and its row is upserted to `UNKNOWN` at startup.
- `_tick`: `_prepare` → ring push → hands → detector → freshness → `_serve_requests` → `_step_wear` → `_publish_view`. Skipped: `change.update`, `_run_people`, `_step_enroll`, `_step_touch`, `_step_trackers`.
- Freshness: hash of the frame downscaled to 32×18 gray; `fresh = False` once the same hash is seen on 10 consecutive ticks; `metrics["camera_lost"] = not fresh`.
- `_step_wear` (on detector ticks): boxes = detector boxes whose id is an enabled item or `"*"`, top `MAX_BOXES` by conf; one `embedder.embed` call; per tracker, `Identity.score_embeddings` against its gallery, best by sim; `accepted = identity.accepts(sim, margin, reacquire=tracker.phase in ("UNTRACKED","PLACED_GONE","WITH_YOU"))`. On non-detector ticks each tracker is stepped with `looked=False, cand=None`. Sharpness = variance of `cv2.Laplacian` on the gray crop; accepted, hand-free candidates are offered to the item's `BestFrame` (frame copy downscaled to ≤ 1280 px wide; box scaled the same).
- Events go through `_emit`. For `SEEN`, pass `frame=` the BestFrame's frame and use its box (fall back to the current frame and `tracker.bbox` if empty); write label `"last seen"`. Then clear that BestFrame.
- `_publish_view` additionally stores the `WearStatus` list.
- `fixed` mode: unchanged code path.

- [ ] **Step 1: Write failing tests** (`WearRig(tmp_path, ...)` = `Rig` with `cfg.camera.mode = "wearable"`, `ZoneMap([])`, a saved airpods gallery, `placed_on_tray=False`):
```python
def test_wearable_touch_put_down_writes_placed(tmp_path):   # hand on case ≥0.5 s, release, case visible 6 ticks -> store row state "PLACED", one PICKED_UP + one PLACED event
def test_wearable_out_of_view_writes_seen_snapshot(tmp_path): # after PLACED, 10 ticks without the case -> a SEEN event whose snapshot_path exists; WearStatus.phase == "PLACED_GONE"
def test_wearable_starts_untracked(tmp_path):              # store pre-seeded with airpods PLACED; new WearRig -> row state "UNKNOWN", status phase "UNTRACKED", no events
def test_wearable_skips_change_and_people(tmp_path):        # FakePeople.calls == 0 and FakeTouch.enabled == [] after 5 ticks
def test_identical_frames_are_stale(tmp_path):              # 12 ticks of the same frame -> wear_status()[1] is False, metrics["camera_lost"] True; a different frame -> fresh again
def test_disabled_item_not_tracked(tmp_path):               # items airpods(enabled)+keys(enabled=False, gallery saved) -> trackers only has airpods
```
- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/test_vision_loop.py -q`. Expected: new tests FAIL, old ones PASS.
- [ ] **Step 3: Implement** in `vision_loop.py` (wearable branch methods: `_step_wear`, `_freshness`; `wear_status`).
- [ ] **Step 4: Run** the suite. Expected: PASS.
- [ ] **Step 5: Commit** `feat: vision loop wearable path (global matching, freshness, last-seen snapshot)`.

---

### Task 4: Answer engine — wearable templates and `answer_item`

**Files:**
- Modify: `lastseen/brain/answer.py`
- Test: `tests/test_answer.py`

**Interfaces:**
- Produces:
  - `fmt_ago(ts: float | None, now: float) -> str` (module function, rules in Global Constraints).
  - `AnswerEngine.answer_item(item_id: str, source: str) -> dict`: same result dict, ask logging and `show_answer` publish as `ask()`, but skips question parsing. Logged question text: `f"[{source}] {item_id}"`.
  - In wearable mode `_find` uses these templates (`it` = "them"/"it" as today):
    - `UNKNOWN` (never touched this session, or item disabled): "Sorry, I did not see you interact with your {name}."
    - `PLACED`: "You put your {name} down {ago}. I put a photo of where on the screen." with `ago = fmt_ago(ts of last PLACED/SEEN event, time.time())`
    - `HELD`: unchanged ("You're holding {it} right now.")
    - `CARRIED_OUT`: "You picked up your {name} at {time} and had {it} with you."
  - The snapshot returned is the latest event with a snapshot (unchanged `_snapshot`), so it's the `SEEN` best frame once the item went out of view.

- [ ] **Step 1: Write failing tests**:
```python
def test_fmt_ago():  # (now-20)->"just now", (now-60)->"1 minute ago", (now-180)->"3 minutes ago", (now-7200)->"at " + fmt_time(now-7200)
def test_wearable_placed_answer(...):     # mode wearable, row PLACED, PLACED event 120 s ago -> text == "You put your AirPods down 2 minutes ago. I put a photo of where on the screen."
def test_wearable_untouched_answer(...):  # row UNKNOWN -> "Sorry, I did not see you interact with your AirPods."
def test_wearable_disabled_item_answer(...): # "where are my keys" with keys enabled=False -> "Sorry, I did not see you interact with your keys."
def test_wearable_with_you_answer(...):   # row CARRIED_OUT -> "You picked up your AirPods at {fmt_time} and had them with you."
def test_answer_item_logs_and_publishes(...): # answer_item("airpods","proactive") -> store.recent_asks(1)[0]["source"] == "proactive"; bus got show_answer
```
(LLM off in these tests; `features.chalk_llm = False`.)
- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/test_answer.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the suite. Expected: PASS.
- [ ] **Step 5: Commit** `feat: wearable answer templates and answer_item`.

---

### Task 5: LostSightAsker — timers, group rule, dialog, dismiss

**Files:**
- Create: `lastseen/proactive/__init__.py`, `lastseen/proactive/lost_sight.py`, `tests/test_lost_sight.py`

**Interfaces:**
- Consumes: `WearStatus` (Task 3), `WearableCfg`, `ItemCfg`, `parse_question` / `resolve_item` from `lastseen/brain/intents.py`.
- Produces:
  - `parse_reply(text: str) -> Literal["yes", "no"] | None`. No-phrases are checked first: `\bno\b`, `nope`, `i know`, `i'm fine`, `i'm good`, `not really`, `never mind`. Then yes-words: `yes|yeah|yep|yup|i am|sure|please|where`.
  - `class LostSightAsker(cfg: WearableCfg, items: list[ItemCfg], say: Callable[[str], None], is_speaking: Callable[[], bool], answer_item: Callable[[str, str], dict], clock: Callable[[], float] = time.monotonic)` with:
    - `tick(statuses: list[WearStatus], fresh: bool) -> None`
    - `on_text(text: str) -> bool` (True = consumed by the dialog)
    - `dismiss(item_id: str) -> bool` (False if the item is unknown or never tracked)
    - `view() -> dict[str, dict]`: per item `{"unseen_s": float, "silenced": bool, "asking": bool}`, effective unseen time
  - `run_asker(asker, loop, bus, stop: threading.Event, period: float = 0.25) -> None`: thread body. Every period: `statuses, fresh = loop.wear_status()`, `asker.tick(...)`; every 2nd period, publish bus `wear_status` with `items=[{id, display_name, phase, unseen_s, last_seen_ts, silenced, asking}]` and `camera_lost = not fresh`. Wrapped in try/except per iteration.

Rules (pinned):
```
effective unseen = status.unseen_s - baseline[id]  (baseline 0 by default)
on status.sightings change for id: baseline[id] = 0; silenced.discard(id)
eligible(id) = phase == "PLACED_GONE" and id not in silenced and id not in an open dialog
tick asks only if: fresh, no dialog open, not is_speaking()
due = eligible with effective >= ask_after_s; if any:
    group = eligible with effective >= ask_after_s - group_window_s
    len(group) == 1 -> say "Are you looking for your {display}?"   stage "single"
    else            -> say "Are you looking for something?"        stage "group"
reply deadline: None while is_speaking(); first tick after that sets deadline = now + reply_window_s
deadline passed: stage single/group/which -> baseline[id] = status.unseen_s for each id in the dialog; close
on_text with a dialog open:
    find intent with an item -> say(answer_item(item, "proactive")["text"]); close; True
    stage single: yes -> say answer for the item; close.   no -> silence ids; close.   None -> False
    stage group:  yes -> say "OK, what item are you looking for?"; stage "which", deadline None.  no -> silence all ids; close.  None -> False
    stage which:  item = resolve_item(text) over all config items -> say answer_item(item)["text"]; close.
                  no item -> say "Sorry, I didn't catch that."; close.   (both True)
on_text with no dialog -> False
dismiss(id): silenced.add(id); remove id from an open dialog; close the dialog if it becomes empty
```
`answer_item` returns the "did not see you interact" text for untracked/disabled items (Task 4), so the asker doesn't special-case them.

- [ ] **Step 1: Write failing tests** (fake clock, `say` collects strings, `is_speaking` from a mutable flag, `answer_item` returns `{"text": f"ANS {id}"}`; helper `st(id, phase="PLACED_GONE", unseen=0.0, sightings=0)`):
```python
def test_parse_reply():   # "yes"->yes, "yeah where"->yes, "no"->no, "nope"->no, "yeah I know where it is"->no, "I'm fine"->no, "know"->None, "hmm"->None
def test_single_question_at_30s():          # unseen 29.9 -> nothing said; 30.0 -> ["Are you looking for your AirPods?"]
def test_group_when_due_within_10s():       # airpods 30.0, keys 21.0 -> ["Are you looking for something?"]
def test_no_group_when_15s_apart():         # airpods 30.0, keys 15.0 -> single airpods question; later keys reaches 30 after the dialog closes -> single keys question
def test_not_asked_when_with_you_or_untracked():  # phases WITH_YOU / UNTRACKED / PLACED_VISIBLE at 100 s -> nothing said
def test_no_ask_when_not_fresh():           # fresh=False at 45 s -> nothing said
def test_reply_window_starts_after_speech():# speaking for 5 s after asking, then 7.9 s quiet -> dialog still open; 8.1 s -> closed, baseline set (no re-ask until another 30 s)
def test_yes_answers_single():              # on_text("yes") -> True; said[-1] == "ANS airpods"
def test_no_silences_until_seen_again():    # "no" -> silenced; unseen 200 s -> nothing; sightings 0->1 then unseen 30 -> asks again
def test_group_yes_then_item():             # "yes" -> "OK, what item are you looking for?"; "my keys" -> "ANS keys"
def test_group_yes_then_gibberish():        # "yes", "banana" -> "Sorry, I didn't catch that."
def test_find_question_during_window():     # dialog open; on_text("where are my keys") -> said "ANS keys", dialog closed
def test_dismiss_during_group():            # group(airpods,keys) open; dismiss("airpods") -> True, dialog open for keys; dismiss("keys") -> dialog closed
def test_dismiss_unknown_item():            # dismiss("nope") -> False
def test_text_without_dialog_not_consumed():# on_text("yes") with no dialog -> False
```
- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/test_lost_sight.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** with one internal lock (tick, on_text and dismiss arrive on different threads). Call `say` outside the lock.
- [ ] **Step 4: Run** the suite. Expected: PASS.
- [ ] **Step 5: Commit** `feat: LostSightAsker (30 s timer, group question, yes/no dialog, dismiss)`.

---

### Task 6: Wiring — voice route, main, /api/dismiss

**Files:**
- Modify: `lastseen/voice/route.py`, `lastseen/__main__.py`, `lastseen/server/app.py`
- Test: `tests/test_voice.py`, `tests/test_main.py`, `tests/test_server.py`

**Interfaces:**
- Consumes: `LostSightAsker`, `run_asker` (Task 5), `AnswerEngine.answer_item` (Task 4), `VisionLoop.wear_status` (Task 3).
- Produces:
  - `make_on_text(engine, speaker, items, dialog=None)`: if `dialog is not None and dialog.on_text(text)` → return True before the existing routing.
  - `AppContext.dismiss_fn: Callable[[str], dict] | None = None`; `POST /api/dismiss {item_id}` (same `ItemId` validation, local-only like other POSTs) → `{"ok": bool}`; 503 when `dismiss_fn` is None.
  - `__main__` in wearable mode: `ZoneMap([])` for the loop and the answer engine; `_make_people` not called (None); classifier/touch not built; `detector.set_items(cfg.enabled_items())` (both modes). When `features.voice` and `features.lost_sight_ask` and the loop and speaker exist: build the asker with `is_speaking=lambda: speaker.speaking.is_set() or time.monotonic() < speaker.muted_until() + 2.5`, `answer_item=engine.answer_item`, pass it as `dialog` to `make_on_text`, start `run_asker` on a daemon thread named `"lost-sight"`, stop it on shutdown, and set `ctx.dismiss_fn = lambda i: {"ok": asker.dismiss(i)}`.

- [ ] **Step 1: Write failing tests**:
```python
# test_voice.py
def test_dialog_gets_text_first():     # dialog.on_text returns True -> engine.ask not called
def test_dialog_declines_falls_through(): # dialog.on_text returns False, "where are my airpods" -> engine.ask called
# test_server.py
def test_dismiss_endpoint():           # ctx.dismiss_fn records calls; POST {"item_id":"airpods"} -> 200 {"ok": True}
def test_dismiss_unavailable():        # dismiss_fn None -> 503
def test_dismiss_bad_id():             # {"item_id":"../x"} -> 422
# test_main.py
def test_wearable_build_skips_people(monkeypatch): # _make_people / touch factories not called in wearable mode (follow the file's existing pattern for _build_vision)
```
- [ ] **Step 2: Run** those files. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the suite, then `timeout 20 .venv/bin/python -m lastseen` and check the log shows "vision loop started" and no traceback (camera may be absent; that's fine).
- [ ] **Step 5: Commit** `feat: wire wearable mode, lost-sight asker and /api/dismiss`.

---

### Task 7: Dashboard — out-of-view, asking, "I know where it is", big snapshot, camera lost

**Files:**
- Modify: `lastseen/server/static/dashboard.html`
- Test: `tests/test_static.py`

**Interfaces:**
- Consumes: bus `wear_status` message (`items[]`, `camera_lost`), `POST /api/dismiss`, existing `show_answer`.
- Produces (UI only):
  - Item card adds: "out of view m:ss" when `phase == "PLACED_GONE"`; an "Asking…" badge when `asking`; "silenced" when `silenced`; a button `I know where it is` (class `dismiss`, `data-item`) enabled when phase is `PLACED_GONE` or `asking` → `post("/api/dismiss", {item_id})`; thumbnail of the item's latest snapshot (already in the item/event data).
  - A `#camlost` banner shown while `camera_lost` is true.
  - `#bigsnap` overlay: on `show_answer` with a `snapshot_url`, full-width image + answer text; closes on click or after 60 s.

- [ ] **Step 1: Write failing test** in `tests/test_static.py`: dashboard.html contains `"wear_status"`, `"/api/dismiss"`, `"I know where it is"`, `id="camlost"`, `id="bigsnap"`.
- [ ] **Step 2: Run** it. Expected: FAIL.
- [ ] **Step 3: Implement** in the page's existing style (plain JS, `el()` helper, no new libraries).
- [ ] **Step 4: Run** the suite; then start the app and open `http://localhost:8000/dashboard` in the browser pane: check the banner, an item card, and that clicking the button returns `{"ok": …}` with no console errors.
- [ ] **Step 5: Commit** `feat: dashboard wearable view (out of view, asking, dismiss, big snapshot)`.

---

### Task 8: Live run on the neck mount (manual, with the user)

**Files:**
- Modify: `config.yaml` (tuned values only), `NOTES.md`, `.plans/wearable-lost-sight-spec.md` §8

- [ ] **Step 1:** User mounts the phone; `python -m lastseen.tools.list_cameras` finds Continuity Camera; `python -m lastseen.tools.reset`; start the app.
- [ ] **Step 2:** Run acceptance tests 1–9 from spec §6 with the AirPods. Record pass/fail per test.
- [ ] **Step 3:** Record measured tick rate, the chosen `detector.every_n`, and the AirPods match rate standing/walking in spec §8. Tune `engine.missing_frames`, `identity.sim_thresh` if needed. Real numbers only.
- [ ] **Step 4:** Note any doc-vs-plan changes in `NOTES.md`. Commit `chore: wearable tuning from live run`.
