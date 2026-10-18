# How reminders use the vision events

The event contract is Amanda's: **`backend/events.py`** (issues #4 and #5), also served at
`GET /api/observations/contract`. This page only explains what the reminder engine
(`backend/reminders.py`) does with each event. Nothing extra has to be emitted for reminders.

## Where events come from

`vision.py` records every event in the `observations` table, with its photo id attached once the
photo is written. The reminder engine reads that table by `seq` cursor on its own thread, so it
never slows the camera loop. Events recorded before the backend started are ignored.

## What each event does to a reminder

| `event_type` (events.py) | High-Assistance | Everyday |
|---|---|---|
| `object_observed` | Starts a cautious reminder (if conf ≥ 0.45). A hand-near event within 60 s before it makes it a placement candidate. Seeing it again never restarts the timer. | Recorded only |
| `interaction_candidate` | Recorded. **Never** cancels anything: proximity isn't contact. | Same |
| `possible_pickup` | Cancels a pending reminder at conf ≥ 0.55 (events.py emits 0.55–0.7, always with `hand_near_object`) | Same |
| `placement_confirmed` | Starts a reminder (replaces any older one) | Starts a reminder if conf ≥ 0.6 |

A reminder becomes due once the item has been **out of the wearer's view** for the mode's delay
(15 s or 150 s). It needs a real photo:
a placement whose photo doesn't arrive within 15 s is dropped. See the
[README](README.md) for every cancellation rule.

## Other producers

Something outside `vision.py` can send the same JSON:

```sh
curl -X POST http://127.0.0.1:8000/api/reminders/events -H 'X-Keepsake-Local: 1' \
  -H 'Content-Type: application/json' -d '{"event_id": "...", "event_type": "possible_pickup", ...}'
```

or call `reminders.ingest(event)` in-process, which only queues it. Repeated `event_id`s are
ignored, and a `snapshot_id` only counts if that photo exists and shows the same item.
