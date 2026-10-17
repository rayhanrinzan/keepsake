# Keepsake Departure Alerts (Photon Spectrum)

When someone appears to leave the room, Keepsake checks where it last saw your important items and
sends an iMessage reminder through [Photon Spectrum](https://photon.codes/docs/spectrum-ts):

> Heads up: your keys were last seen on the couch at 10:32 AM. Looks like you might be heading out. Did you bring them?

Keepsake can't see into pockets or know that you actually left, so reminders are suggestions based
on the last observation, never claims that something was forgotten.

```
backend (Python)                                 integrations/photon (TypeScript)
vision.py person boxes ─► departure.py ─► GET /api/departures ◄─ poll ─ departures.ts
                                          GET /api/objects, /context ──► alerts.ts (eligibility)
                                                                      ─► notifier.ts ─► Photon ─► iMessage
                                          POST /api/query ◄── inbound.ts ◄── replies from your phone
```

The backend only reports possible departures; it never makes network calls, so Keepsake keeps
working when the agent or Photon is offline. The agent never reads the SQLite database directly.

## Run

```sh
# 1. Keepsake backend, from Terminal.app (camera permission is per app)
cd backend && ../.venv/bin/python main.py

# 2. The agent (needs the backend running)
cd integrations/photon && npm install && npm run start
```

Startup prints whether alerts are ON, how many recipients are authorized and which items are watched.

## Configure (`.env`, git-ignored; see `.env.example`)

| Variable | Default | |
|---|---|---|
| `PROJECT_ID`, `PROJECT_SECRET` | | Spectrum project credentials (written by `create-spectrum-project`) |
| `ALERTS_ENABLED` | `false` | Master switch. Nothing from Keepsake memory is sent until it's `true` |
| `ALERT_RECIPIENTS` | | Comma-separated E.164 numbers. On Free/Pro each must be a project user: `photon spectrum users add` |
| `IMPORTANT_ITEMS` | `keys,wallet,phone` | Catalog categories, names or aliases (`/api/catalog`); any tracked item works for demos |
| `ALERT_MAX_AGE_MINUTES` | `180` | Ignore observations older than this |
| `ALERT_COOLDOWN_MINUTES` | `15` | Don't mention the same item again sooner |
| `DEPARTURE_MAX_EVENT_AGE_SECONDS` | `120` | Ignore stale departure events |

An item is included only if it has a real recorded location in the current camera view, is recent
enough, isn't moving or "lost while moving", and isn't in cooldown. No alert is sent while the camera
is repositioning, scanning, shifted or dark. Several items are combined into one message; each
departure is handled once and failed sends are not retried. `.data/state.json` keeps handled event
ids, per-item cooldowns and the pause flag (no phone numbers or message text).

## Exit zone (automatic departures)

The detector is off until you set an exit zone in normalized camera coordinates
(`[x0, y0, x1, y1]`, e.g. the doorway at the right edge):

```sh
curl -X PUT http://127.0.0.1:8000/api/departures/config -H 'Content-Type: application/json' \
  -d '{"enabled": true, "exit_zone": [0.85, 0, 1, 1]}'
curl http://127.0.0.1:8000/api/departures/context   # detector state, hold reason, person count
```

A possible departure needs one person to be seen in the room, move into the exit zone, then stay
out of view for 2.5 s (brief detection dropouts don't count). More than one person, Scan room,
camera shifts, dark frames, detection errors and frame gaps all suppress it. There is no face or
identity recognition. This is tuned on synthetic tests; tune on the real camera before relying on it.

## Manual test

With the backend and agent running:

```sh
npm run trigger:departure
```

This records a simulated departure (local only: needs the `X-Keepsake-Local` header). The agent then
evaluates the real stored memories and either sends a real iMessage or logs why it didn't
(`no_eligible_items`, `camera_repositioning`, …).

## Text the agent

From an authorized number, text the project's assigned number (`photon spectrum users list --json`
→ `assignedPhoneNumber`):

- "Where are my keys?": Keepsake's own answer from `/api/query`
- "Pause reminders" / "Resume reminders"
- "I have them"
- "Hello Photon": connectivity check

Messages from other numbers are ignored.

## Test

```sh
npm test            # alert rules, client, service, inbound (mocked network)
npm run typecheck
../../.venv/bin/python -m pytest ../../tests/test_departure.py   # detector + endpoints
```
