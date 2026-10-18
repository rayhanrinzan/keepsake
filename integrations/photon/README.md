# Keepsake smart memory reminders (Photon Spectrum)

Keepsake can text you a gentle reminder about belongings it recently saw you with:

> Keepsake reminder: Your wallet was last seen at 2:34 PM. Check whether you have it.
> *(followed by the photo of where Keepsake last saw it)*

Reminders go out through [Photon Spectrum](https://photon.codes/docs/spectrum-ts) iMessage. They're
built only from what Keepsake actually recorded: a real photo and the time of the last sighting.
A wearable camera can't see pockets or bags, so a reminder never says you forgot something.

This is a hackathon prototype for memory support. It is **not** a clinically validated assistive
or monitoring device, and reminders are not emergency or medical alerts.

```
backend (Python)                                        integrations/photon (TypeScript)
vision events (events.py) ──► reminders.py policy ─► GET /api/reminders/alerts ◄─ poll ─ reminders.ts
                                (state per item)       claim → send → result ───────────► Photon ─► iMessage
                                                        /ack, /check, /settings ◄── inbound.ts ◄── your replies
```

The backend decides *whether* to remind. It makes no network calls and runs on its own thread, so
Keepsake works normally when the agent or Photon is offline. The agent only checks its recipient
allowlist, formats and sends the text, and reports `accepted` or `failed`. **`accepted` means
Spectrum took the send request, not that the phone received it.**

**Photos are sent.** Each reminder carries the real last-seen photo of each item (up to 3), and a
"where is my …?" reply carries that item's photo. Those photos leave the Mac: they go through Photon
and iMessage to the authorized recipients. They're full camera frames, so they can show whatever else
was in view. If a photo can't be fetched, the text still goes out.

## Modes

One policy engine with two presets. `off` is the default.

| | High-Assistance | Everyday |
|---|---|---|
| For | People who choose frequent memory support | Fewer, higher-confidence reminders |
| Triggers | Confirmed placement; hand-near-then-stable; or a stable photo-backed sighting (cautious wording) | Confirmed placement (confidence ≥ 0.6), or an explicit "heading out" check |
| Delay | 15 s out of view | 150 s out of view |
| Per-item cooldown | 5 min | 30 min |
| Global cooldown | 60 s | 10 min |
| Wording | "Keepsake reminder: … Check whether you have it." | "Heading out? … Check whether you have it." |

Both modes:
- **One reminder per placement.** Seeing the same item again doesn't restart its timer.
- **Batching:** several due items go out in one message.
- **Snooze** gives one more reminder later.
- **Cancellation:** a pending reminder is dropped on any of these:
  - a confident pickup (≥ 0.6)
  - a newer placement
  - "I have it"
  - a mode change or pause
  - the camera disconnecting, going dark or freezing
  - the item being lost while moving
  - a missing or stale photo
  - cooldown or age

**Separation** is what makes a reminder due: the item has been out of the wearer's view for the
mode's delay. This is a weak signal: it means the camera turned away, not that the item stayed behind.
An explicit "heading out" text or the manual check also counts. Reminders never name a room area.

## Run

```sh
cd backend && ../.venv/bin/python main.py          # Keepsake backend (from Terminal.app)
cd integrations/photon && npm install && npm run start
```

## Turn reminders on (explicit opt-in)

Both sides have to be on:

1. **Photon side** (`integrations/photon/.env`, git-ignored): `ALERTS_ENABLED=true`, plus
   `ALERT_RECIPIENTS=+1…` (E.164; on Free/Pro also a project user via `photon spectrum users add`).
2. **Keepsake side:** from an authorized phone, text **"high assistance"** or **"everyday"**. Or locally:

```sh
curl -X PUT http://127.0.0.1:8000/api/reminders/settings -H 'X-Keepsake-Local: 1' \
  -H 'Content-Type: application/json' \
  -d '{"mode": "high_assistance", "enabled": true, "opt_in": true, "important": ["wallet", "bottle", "keys"]}'
```

Settings persist in Keepsake's database. Per-mode tuning goes in `overrides` (per mode: `delay`, `min_confidence`, `per_item_cooldown`, `global_cooldown`,
`max_photo_age`, `max_pending`, `pickup_cancel_conf`, `snooze`). Inspect everything, including each
item's state and recent decisions, with `GET /api/reminders/settings`.

## Text commands (authorized numbers only)

| Text | Effect |
|---|---|
| "high assistance" / "everyday" / "reminders off" | Choose a mode (texting a mode is the opt-in) |
| "I have it" | Dismiss the latest reminder |
| "remind me later" | One more reminder after the snooze time |
| "pause reminders" / "resume reminders" | Pause and resume |
| "heading out" | Check now against the selected mode's rules |
| "where are my keys?" | Keepsake's own answer from `/api/query` |

## Manual test (P0)

With both processes running, real memories in Keepsake (point the camera at a wallet or bottle),
and a mode turned on:

```sh
npm run reminder:check               # labelled "manual" everywhere
npm run reminder:check heading_out   # same as texting "heading out"
```

This never injects a placement or a detection. The engine evaluates the real stored memory and
either queues a reminder, which the agent then sends, or prints why each item was skipped.

## Hand-interaction events

Amanda's vision pipeline (`backend/events.py`, `wearable.py`, `hands.py`) emits `object_observed`,
`interaction_candidate`, `possible_pickup` and `placement_confirmed`. The engine reads them
directly; [EVENTS.md](EVENTS.md) explains what each one does to a reminder. Hand detection needs
MediaPipe and its model (see `backend/hands.py`). Without it, only `object_observed` is emitted
and reminders fall back to the cautious High-Assistance path.

## Test

```sh
npm test && npm run typecheck                                          # agent (mocked network)
../../.venv/bin/python -m pytest ../../tests/test_reminders.py         # policy engine + API
```
