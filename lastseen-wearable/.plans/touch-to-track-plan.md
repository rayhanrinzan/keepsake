# Touch-to-Track Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Lock onto one of the four configured items (AirPods, glasses, playing cards, water bottle) automatically when a hand touches it and lets go. No enroll command needed.

**Architecture:** A `TouchWatcher` follows each hand as an "episode", using the ChangeDetector to find what changed when the hand leaves. An `ItemClassifier` uses CLIP's text encoder to decide which of the still-unlocked items it is, with a strict confidence rule. The VisionLoop then builds that item's gallery with the existing enrollment finalize step, creates its tracker, and writes one event with one snapshot. Everything after the lock is the existing tracker.

**Tech Stack:** Python 3.12, OpenAI `clip` (ViT-B/32, already loaded; `encode_text`), OpenCV, existing `lastseen` package, pytest.

**Spec:** `.plans/airpods-full-loop-spec.md` §4.13 (touch-to-track) and §4.12 (items). Builds on `.plans/airpods-full-loop-plan.md` (Tasks 1–11b, done).

## Global Constraints

- Items exactly: `airpods`, `glasses`, `playing_cards`, `water_bottle` (this order), all `critical: false`. Nothing outside these is ever named.
- Files are written only at events (one snapshot per lock/put-down); the ring buffer stays in memory. Clips at events sit behind `features.clips` (default true).
- Touch-to-track sits behind `features.touch_to_track` (default true) and is suppressed while a manual enroll session runs.
- Accept a classification only if the top class is an item, its probability is ≥ **0.45**, and it leads the next class (items and "other" together) by ≥ **0.15**. Otherwise lock nothing and log the probabilities.
- Hand episodes: an episode ends after **3** consecutive ticks with its hand absent, having been present ≥ **0.5 s**; shorter presences are flickers.
- At most one new lock per tick. Releases on an already-tracked item's bbox or live_box (IoU > 0.1) are ignored.
- No SQLite schema change. Origin `"auto"` lives only in `data/gallery/<item>/meta.json`.
- All ChangeDetector calls stay on the vision thread. Every per-tick step is in try/except (log, continue). Tests never load CLIP, YOLO or MediaPipe.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Never `git add` anything under `.superpowers/`.

## Review Focus

1. **A single-frame hand dropout in the middle of a touch** must not end the episode early. Test in Task 3.
2. **Touching or moving an item that's already locked** creates no second lock; its tracker handles it. Test in Task 4.
3. **Two hands in view at once** give two episodes, and at most one lock per tick. Tests in Tasks 3 and 4.
4. **An unsure classification** (e.g. a mug, or glasses vs cards too close) locks nothing and logs the probabilities. Tests in Tasks 2 and 4.
5. **Manual enroll running:** touch episodes are closed and their change references dropped while it runs. Tests in Tasks 3 and 4.

---

### Task 1: Items and feature flags

**Files:** Modify `config.yaml`, `lastseen/config.py`, `lastseen/engine/vision_loop.py` (clip writing in `_emit`), `tests/test_config.py`, `tests/test_vision_loop.py`

**Interfaces:**
- Produces: `FeaturesCfg.clips: bool = True`, `FeaturesCfg.touch_to_track: bool = True`; config items in the order airpods, glasses, playing_cards, water_bottle.

- [ ] **Step 1: Update the tests first.** In `tests/test_config.py`, the item list assertion becomes `["airpods","glasses","playing_cards","water_bottle"]`, plus `assert cfg.features.clips is True and cfg.features.touch_to_track is True`. In `tests/test_vision_loop.py`, add `test_no_clip_when_clips_disabled`: with `cfg.features.clips = False`, a PLACED event has a `snapshot_path` and `clip_path is None`.
- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/test_config.py tests/test_vision_loop.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.**
  - **config.yaml:** replace the `sleeping_mask` item with `water_bottle` exactly per spec §4.12 (display `water bottle`, prompt `water bottle`, extra `[bottle, reusable bottle, drink bottle]`, synonyms `[water bottle, bottle, my bottle, water]`), keeping the order above.
  - **config.py:** add the two flags.
  - **`_emit`:** call `write_clip` only when `cfg.features.clips`.
- [ ] **Step 4: Run** the whole suite with `-W error`. Expected: PASS. Fix any test that hard-coded `sleeping_mask`.
- [ ] **Step 5: Commit** `feat: water bottle replaces sleeping mask; clips and touch-to-track flags`.

---

### Task 2: CLIP text classifier

**Files:** Modify `lastseen/vision/embedder.py`. Create `lastseen/vision/classify.py`, `tests/test_classify.py`. Add a text method to `FakeEmbedder` in `tests/fakes.py`.

**Interfaces:**
- Produces `ClipEmbedder.embed_text(texts: list[str]) -> np.ndarray` (N, 512), L2-normalized, from the already-loaded model's `encode_text(clip.tokenize(texts))`.
- Produces `OTHER_PROMPTS = ["a hand", "a table", "a phone", "a cup", "a pen", "background"]`.
- Produces `@dataclass Classification(item_id: str | None, probs: dict[str, float], reason: str)`. `probs` has one key per candidate item plus `"other"`. `reason` is one of `"ok"`, `"other"`, `"low"`, `"close"`.
- Produces `ItemClassifier(embedder, items: list[ItemCfg], min_prob=0.45, min_lead=0.15, det_boost=0.03, scale=100.0)` with `classify(frame, box: Box, det_item_ids: list[str], candidates: list[str]) -> Classification`. At construction it precomputes one text embedding per item (mean of its normalized prompt and extra-prompt embeddings, renormalized) and one per OTHER prompt.

Algorithm (pinned):
```
img = embedder.embed(frame, [box])[0]
logit(item) = scale * (img · text(item) + (det_boost if item in det_item_ids else 0))   for item in candidates
logit(other_k) = scale * (img · text(other_k))
softmax over all those logits; probs["other"] = sum of the other_k probabilities
top = argmax over {candidate items..., "other"}
if top == "other": reason "other"
elif probs[top] < min_prob: "low"
elif probs[top] - max(the remaining probs, including "other") < min_lead: "close"
else: item_id = top, reason "ok"
```

- [ ] **Step 1: Write failing tests** in `tests/test_classify.py`. Use a scripted embedder: `embed` returns a fixed image vector, and `embed_text` returns hand-picked unit vectors per text. That makes the probabilities controllable.
```python
def test_clear_match_locks(): img aligned with "airpods case" → item_id == "airpods", reason "ok"
def test_other_wins(): img aligned with "a cup" → item_id is None, reason "other"
def test_close_call_rejected(): img halfway between glasses and playing_cards → None, reason "close"
def test_low_confidence_rejected(): img nearly orthogonal to everything → None, reason in ("low","other")
def test_only_candidates_considered(): airpods excluded from candidates → never returned even when best
def test_det_label_boost_breaks_tie(): halfway glasses/cards, det_item_ids=["glasses"] with det_boost large enough → "glasses"
def test_probs_keys(): set(c.probs) == set(candidates) | {"other"} and abs(sum(c.probs.values()) - 1) < 1e-6
```
- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/test_classify.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement `embed_text`, `ItemClassifier` and `FakeEmbedder.embed_text`.** FakeEmbedder's version is a deterministic text → unit vector, e.g. seeded by a stable hash of the text. Add `ClipEmbedder.embed_text` to the `models` smoke test: 4 texts give shape (4, 512) with unit norms. Run it once with `--run-models` and put the output in the report.
- [ ] **Step 4: Run** the whole suite with `-W error`. Expected: PASS.
- [ ] **Step 5: Commit** `feat: clip text classifier over the configured items`.

---

### Task 3: TouchWatcher (hand episodes)

**Files:** Create `lastseen/engine/touch.py`, `tests/test_touch.py`

**Interfaces:**
- Consumes: `ChangeDetector.snapshot() -> int`, `blobs(ref, frame, near, radius) -> list[Box]`, `drop(ref)`; `EngineCfg.near_hand_px`, `move_px`.
- Produces `@dataclass TouchResult(kind: Literal["placed","lifted"], box: Box, frame: np.ndarray, ts: float, last_hand: tuple[int,int])`.
- Produces `TouchWatcher(change: ChangeDetector, engine_cfg, max_episodes=2)` with:
  - `update(frame, ts, hands: list[Box], enabled: bool = True) -> list[TouchResult]`
  - `close_all() -> None`
  - `active() -> int`, the number of open episodes.

Rules (pinned):
- **Matching hands to episodes:** each tick, match each hand to the open episode whose last hand center is nearest, within 1.5 × near_hand_px (greedy, nearest first). Unmatched hands open a new episode, up to max_episodes. Opening an episode takes `change.snapshot()`, stores `frame.copy()` as the "before" frame, and records `first_center` = `last_center` = the hand center and `first_ts`.
- **Updating episodes:** a matched episode updates `last_center` and `last_ts` and resets its absent count. An unmatched episode increments its absent count. At 3, the episode ends. If `last_ts − first_ts` < 0.5 s it was a flicker: drop the ref and return nothing.
- **When an episode ends:**
  - `placed` = `blobs(ref, frame, near=last_center, radius=near_hand_px)`. When first_center and last_center are ≥ move_px apart, discard blobs whose center is closer to first_center than to last_center (that's the vacated spot). If any remain, the nearest to last_center gives `TouchResult("placed", box, frame (current), ts, last_center)`.
  - Otherwise `vacated` = `blobs(ref, frame, near=first_center, radius=near_hand_px)`. If any, the nearest gives `TouchResult("lifted", box, before_frame, ts, last_center)`.
  - Otherwise nothing.
  - Always `drop(ref)`.
- **`enabled=False`:** call close_all() (drop every ref, no results) and return [].

- [ ] **Step 1: Write failing tests** with a real ChangeDetector on synthetic 640×360 frames (gray background, white rectangle item, skin-coloured square hand) and explicit ts. Call `change.update` on the background first, as the vision loop does.
```python
def test_put_down_reports_placed(): hand brings item in, sets it down, leaves (3 absent ticks) → one "placed" with box IoU>0.5 vs item
def test_move_reports_new_spot_not_vacated(): item at A, hand lifts it, moves 200 px, puts it at B, leaves → "placed" box at B (IoU>0.5), not A
def test_lift_and_leave_reports_lifted(): item at A, hand lifts it and leaves with it → "lifted", box at A, frame is the before frame (item visible in it)
def test_brush_reports_nothing(): hand hovers over item 1 s, leaves, item unmoved → []
def test_flicker_ignored(): hand present 0.3 s → [] and no ref left (change._refs empty)
def test_single_frame_dropout_does_not_end(): hand present 1 s, missing 1 tick, present again → no result yet; active() == 1   # Review Focus 1
def test_two_hands_two_episodes(): two hands far apart → active() == 2   # Review Focus 3
def test_disabled_closes_episodes(): open episode, update(enabled=False) → [] and refs dropped   # Review Focus 5
```
- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/test_touch.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement `TouchWatcher`** per the rules.
- [ ] **Step 4: Run** the whole suite with `-W error`. Expected: PASS.
- [ ] **Step 5: Commit** `feat: touch watcher — hand episodes find placed or lifted items`.

---

### Task 4: Lock on touch in the vision loop, plus forget

**Files:** Modify `lastseen/engine/enroll.py`, `lastseen/engine/vision_loop.py`, `lastseen/server/app.py`, `lastseen/__main__.py`, `tests/test_vision_loop.py`, `tests/test_server.py`, `tests/fakes.py`

**Interfaces:**
- Consumes: Task 2 `ItemClassifier.classify`; Task 3 `TouchWatcher.update` / `TouchResult`; existing tracker / store / `_emit`.
- Produces `enroll.build_gallery(frame, box, item_id, display_name, prompt, ts, embedder, identity, gallery_root, det_boxes, origin: str = "enrolled") -> tuple[Box, Gallery]`, the renamed `_finalize`. All existing callers keep passing through it; meta origin comes from the parameter.
- Produces `VisionLoop(..., classifier=None, touch=None)`. Touch-to-track runs only when both are given and `features.touch_to_track` is set.
- Produces `VisionLoop.forget(item_id) -> dict`, queued to the vision thread like click_enroll (inline when the thread isn't alive). It removes the tracker, the gallery and the `data/gallery/<item_id>` dir, drops any change ref, and upserts the item UNKNOWN (zone None, bbox None). Returns `{"ok": True}`, or `{"ok": False}` for an unknown item.
- Produces `AppContext.forget_fn` and `POST /api/forget {item_id}` → 503 when None.

Rules (pinned):
- **Per tick, after `_step_enroll`:**
  - If there's no session: `results = touch.update(frame, ts, hands, enabled=True)`.
  - If a session is active: `touch.update(frame, ts, hands, enabled=False)`.
  - For the first result whose box overlaps no tracker's `bbox` or `live_box` (IoU > 0.1): `candidates` = config items without a tracker. If there are none, skip.
  - `det_item_ids` = item ids of detections with IoU > 0.3 vs the box.
  - `c = classifier.classify(result.frame, result.box, det_item_ids, candidates)`.
  - If `c.item_id` is None: `logger.info("touch: not locking (%s) %s", c.reason, rounded probs)`, and stop.
- **"placed":**
  - `box, g = build_gallery(result.frame, …, origin="auto")`.
  - Lock through a refactored `_lock_item(item_id, box, gallery, state="PLACED")`: the common part of `_finish_enroll`, which `_finish_enroll` now also calls.
  - It emits PLACED (confidence = round(probs[item], 2)) with one snapshot, and logs `touch: locked <item> (p=…)`.
- **"lifted":**
  - Build the gallery from `result.frame` (the before frame) and lock the tracker.
  - If `last_hand` is within 5% of a frame edge: emit `CARRIED_OUT` (to_zone None, snapshot from the before frame), and the tracker becomes CARRIED_OUT.
  - Otherwise: emit `PICKED_UP` (from_zone = the zone of the box), and the tracker becomes HELD with its anchor at `last_hand`.
  - Add a small public `ItemTracker.restore` path (or a `start_held(anchor, ts)` method) for this. Keep the tracker change minimal.
- **Isolation:** the whole touch step is in try/except (`_log_exc("touch")`).
- **`__main__`:**
  - Build `ItemClassifier(embedder, cfg.items)` and `TouchWatcher(change, cfg.engine)` and pass them in.
  - Wire `ctx.forget_fn = loop.forget`.

- [ ] **Step 1: Write failing tests** (fakes only; a FakeClassifier returning scripted Classifications; synthetic frames as in Task 3):
```python
def test_touch_locks_untracked_item(): put-down episode + FakeClassifier→"airpods" → tracker exists, one PLACED event with snapshot_path, gallery meta origin "auto"
def test_touch_unsure_locks_nothing(caplog): classifier returns None/"close" → no tracker, no event, log line contains "not locking"   # Review Focus 4
def test_touch_on_tracked_item_ignored(): release box overlaps an existing tracker's bbox → classifier never called, no new lock   # Review Focus 2
def test_one_lock_per_tick(): two results in one tick, both classifiable → only one new tracker that tick   # Review Focus 3
def test_touch_suppressed_during_enroll(): start_enroll active → touch.update called with enabled=False   # Review Focus 5
def test_lifted_at_edge_is_carried_out(): lifted result with last_hand at the frame edge → CARRIED_OUT event, tracker state CARRIED_OUT
def test_lifted_in_view_is_held(): lifted result mid-frame → PICKED_UP event, tracker HELD
def test_forget_removes_tracker_and_gallery(tmp_path): lock, forget → no tracker, gallery dir gone, store row UNKNOWN
def test_manual_enroll_still_works(): existing start_enroll → done path unchanged (origin "enrolled")
```
Add `test_forget_503_and_calls` to `tests/test_server.py`.
- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/test_vision_loop.py tests/test_server.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** per the rules. Keep vision_loop.py readable. If it passes ~600 lines, move the touch step into a small helper in `lastseen/engine/touch.py` (e.g. `def handle_touch(loop, …)`) and report it.
- [ ] **Step 4: Run** the whole suite with `-W error`. Then run the live smoke as in earlier tasks: replay video, `/health` vision_tps ≥ 6 with touch on. Expected: PASS.
- [ ] **Step 5: Commit** `feat: lock onto items by touch; forget endpoint`.
