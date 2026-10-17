
## Elevated-angle test 2026-10-16 (prototype, iPhone via Continuity Camera)

- iPhone was camera **0**, laptop camera **1** on this Mac. The index can change; check with `spikes/corner_check.py --list`.
- iPhone held high, looking down at a desk: the prototype locked on with R and tracked the AirPods case (~55 px wide) on the desk, with a hand typing next to it. The user confirmed it works.
- The prototype's spoken location ("right behind you, up high") is meaningless from above. Expected: the new build answers with zones (spec §4.6).
- Still to measure with `corner_check.py`: detector hit %, CLIP gap per spot, and ankle detection at the door.

## Chalk AI Router

Checked https://docs.chalk.ai/docs/ai-router on 2026-10-16. It matches the brief: OpenAI-compatible, base URL `https://<api host>/v1/router` (`api.chalk.ai` when hosted), `Authorization: Bearer <router key>`, header `X-Chalk-Env-Id`. Difference: the docs name **no default chat model** (`model` is required, e.g. `openai/<model>`, discover with `chalk router model list`), so `CHALK_MODEL` is required in `.env`; without key, host and model the client stays off and template answers are used.

## Prototype → package

The single-file prototype now lives in `legacy/` (`legacy/run_demo.sh` still runs it; `spikes/corner_check.py` imports it from there). Its working parts were ported into the `lastseen/` package:

- `LatestFrame` (latest-frame-only grabber) → `lastseen/capture/camera.py`
- `Embedder` (OpenAI CLIP ViT-B/32 crops) → `lastseen/vision/embedder.py`
- `Tracker`'s CLIP gallery, background negatives, margin follow/reacquire and template fallback → `lastseen/vision/identity.py`
- `iou` / `clamp_box` → `lastseen/vision/geometry.py`
- `SpeechListener` → `lastseen/voice/listen.py`
- `render_answer` look (circled item + label on the snapshot) → `lastseen/memory/clips.py`
- Not ported: CSRT box following, the camera-relative spoken location ("behind you, up high"; replaced by zones) and the OpenCV window UI (replaced by `/dashboard` and `/frame`).
