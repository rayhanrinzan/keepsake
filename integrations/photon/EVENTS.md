# Reminder event contract (vision → reminders)

How object and hand-interaction evidence reaches Keepsake's reminder engine (`backend/reminders.py`).
This is the proposal for issues #4 and #5. The field names are open to change, but agree on any
change with the Photon owner first.

## What already works without any new events

The engine reads Keepsake's own **snapshot rows**, so every confirmed sighting that memory stores
with a photo becomes an `object_observed` automatically. Nothing new has to be emitted for that
path. What the engine **can't** get today is evidence that a hand handled the item. That's what
these events add.

## Sending events

Either call the engine from the same process (it only appends to a queue, so it never blocks the
camera loop):

```python
reminders.ingest(event_dict)          # main.reminders
```

or post over localhost:

```sh
curl -X POST http://127.0.0.1:8000/api/reminders/events \
  -H 'X-Keepsake-Local: 1' -H 'Content-Type: application/json' -d '{...}'
```

The HTTP response says what happened: `scheduled`, `candidate`, `recorded`, `cancelled`,
`updated`, `observed` (with a `why`), or `duplicate`. A 422 means the event broke the contract.

## Fields

| Field | Required | Notes |
|---|---|---|
| `event_id` | yes | Unique and stable. A repeated id is ignored, so retries are safe. |
| `event_type` | yes | One of the types below. |
| `object_id` or `category` | yes | Catalog id (`wallet_01`), category (`wallet`) or alias (`phone`). |
| `timestamp` | yes | ISO-8601, UTC preferred. When the evidence happened, not when it was sent. |
| `confidence` | yes | 0–1, calibrated for *this* event type (how sure you are of the interaction, not the detection). |
| `evidence` | no | List of short strings, e.g. `["hand_overlap", "object_lifted", "stable_after_move"]`. Kept for diagnostics. |
| `snapshot_id` | no | Id of a row in the `snapshots` table showing the item. Ignored unless that photo exists *and* belongs to this object. Without one, a placement waits up to 15 s for memory's own photo, then is dropped. |
| `camera_mode` | no | `wearable` or `stationary`. |
| `view_id` | no | `memory.view_id` at the time. |
| `bbox` | no | `[x0, y0, x1, y1]` normalized, in that frame. |

## Event types

| Type | Meaning | What the engine does |
|---|---|---|
| `object_observed` | The item was reliably visible (stable detection). Not proof of handling. | High-Assistance: may schedule a cautious reminder. Everyday: recorded only. |
| `object_reobserved` | Seen again. | Updates grounding; **never** restarts a pending timer. |
| `interaction_candidate` | A hand was near or over the item. Not proof of contact. | Recorded. An `object_observed` within 60 s afterwards counts as a placement candidate in High-Assistance. Never cancels anything. |
| `possible_pickup` | Evidence the item was lifted or handled. | Cancels a pending reminder only at confidence ≥ 0.6 (`pickup_cancel_conf`). |
| `placement_confirmed` | An observed interaction **followed by** the item becoming stable at a new spot. | Schedules a reminder in both modes (Everyday needs confidence ≥ 0.6). |

Please don't emit `placement_confirmed` for a stable detection on its own. Use `object_observed`
for that. Hand occlusion and camera panning shouldn't produce `possible_pickup`.

## Example

```json
{
  "event_id": "hands-2026-10-17T18:34:02Z-wallet-17",
  "event_type": "placement_confirmed",
  "object_id": "wallet_01",
  "timestamp": "2026-10-17T18:34:02Z",
  "confidence": 0.82,
  "evidence": ["hand_overlap", "object_moved_with_hand", "stable_3s_after_release"],
  "snapshot_id": 412,
  "camera_mode": "wearable",
  "view_id": "view-360e51d6"
}
```

The values above illustrate the schema; they aren't a real observation.

## Still missing for fully automatic placement reminders

1. Any `interaction_candidate`, `possible_pickup` or `placement_confirmed` events. Hand tracking
   (issue #5) isn't merged yet, so today only memory's own `object_observed` sightings exist.
2. A `snapshot_id` on interaction events, or a guarantee that memory stores a photo within 15 s of
   a placement. Without a real photo the reminder is dropped.
3. A per-event interaction `confidence`, separate from detector confidence.
