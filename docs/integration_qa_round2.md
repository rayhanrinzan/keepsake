# Integrated-build QA — round 2

Base: `integration/merge-all` at `5c3b62c` (latest fetched GitHub tip on 2026-10-17). Work is isolated on `feature/integration-qa-round2`. The team's existing checkout and running app were not modified or restarted. This round supersedes the previous cross-branch report: the merged base already shares Amanda's catalog, consumes her observation table, and has the current reminder modes.

## Fixed integration failures

- An early wearable sighting could have a persisted photo and reminder while `/api/query` and the frontend reported “never seen.” Canonical object retrieval now uses actual visual observations/photos before the fixed spatial state machine settles. It selects actual sighting/placement evidence by event time, excludes inferred pickup/proximity events, and keeps the matching photo. Newer observations update an older memory's timestamp.
- Wearable voice answers and object/photo labels no longer turn fixed image regions into physical room-location claims. Answers use real item/time/photo evidence and historical wording. Fixed-camera calibration behavior is preserved; its existing API tests explicitly select fixed mode.
- Null wearable locations would crash the frontend's `placeName` formatter. The formatter now accepts a missing location and renders “Last seen.” The integration test renders the actual React ObjectList from the actual Python query response.
- Canceling a pending item did not remove it from an already queued alert. Cancellation now removes only that item's queued payload, retaining other eligible items in the batch.
- An agent could claim an alert after a pickup, deleted photo, disconnect or renewed visibility. Claim now consumes pending evidence and rechecks the current policy/grounding before the send reservation. Production wires in SnapshotStore file-existence checks; missing photos are not advertised as available, and history excludes unavailable files instead of returning null entries.
- Out-of-order events could replace newer reminder episodes. Per-item event timestamps now prevent older state transitions from replacing newer ones.
- Reading the newest 200 observations then advancing the cursor skipped the beginning of a larger backlog. Internal polling now drains oldest-first; public observation ordering remains newest-first.
- Numeric/boolean timestamps could produce HTTP 500. Invalid timestamp types now become the existing contract error/HTTP 422.
- The React app still watches the stationary-camera `person_left_count`. Wearable health now suppresses that counter; manual voice remains available. Roman's `roman/wearable-lost-sight` branch adds a separate `lastseen-wearable` application, not a drop-in feature for this React/FastAPI build. It was inspected, not merged or reimplemented.

No event schema was replaced, no detector/hand/Photon SDK implementation was rewritten, and no production configuration or credentials were read/changed. Small patches to shared modules were presented before applying them to this isolated checkout.

## Verification

- Baseline merged build: **149 Python tests passed**.
- Final full suite with the HTTP bridge enabled: **184 passed**, no expected failures or skips.
- New integration suite: **35 tests**, including the opt-in real HTTP bridge (21 pipeline cases and 14 diagnostic cases).
- Photon agent: **17 tests passed**, all sends mocked.
- Frontend: TypeScript/Vite production build passed.
- Photon agent: TypeScript type check passed.
- One Starlette/httpx deprecation warning remains. Installed Photon dependencies report 18 moderate audit findings; dependencies were not upgraded during integration QA.

The HTTP bridge starts an ephemeral loopback FastAPI server with isolated temporary SQLite/photos and camera/reminder background threads disabled. The production TypeScript KeepsakeClient retrieves a real test memory and JPEG, the production React ObjectList renders that response, and production ReminderDelivery claims, formats, sends through a **fake notifier**, and reports acceptance to Python. A second poll sends nothing. Grok TTS is separately mocked and receives the exact grounded query answer. Neither the Photon live entry point nor the Spectrum sender is imported by this bridge.

Synthetic data is restricted to tests. No real iMessage, paid Grok synthesis, camera-device takeover or fabricated live observation occurred.

## Running-app observations

Passive preflight on existing ports 8000/5173 passed: both preview samples decoded/nonblack, frame IDs advanced, observation and photo retrieval worked, voice/reminder settings responded, and frontend/proxy identities matched. A 15.18-second passive camera sample recorded **67 successful requests, 61 distinct frame IDs, zero failed/black/invalid samples**, about **4.02 observed preview frames/second**. That rate is bounded by polling; it is not sensor FPS.

These checks describe the existing unpatched running app's camera/network state. They do not mean this QA patch was deployed there. Direct production SQLite integrity testing was skipped because its configured path was not supplied. Photon shell configuration was not visible; agent connection and actual handset receipt remain unverified. The previous round's black-frame blocker did not recur in this sample.

## Run and review

Install the repository's normal test dependencies plus locked frontend/agent packages. QA used Python 3.14.4, pytest 9.1.1, NumPy 2.5.4, OpenCV-headless 5.0.0.93, FastAPI 0.143.3 and httpx 0.28.1; expensive inference/hardware are excluded from deterministic tests.

```sh
python -m pytest -q
# Real local HTTP and React/TypeScript bridge; requires node, uvicorn and the locked dependencies:
KEEPSAKE_HTTP_E2E=1 python -m pytest -q
npm run build --prefix frontend
npm test --prefix integrations/photon
npm run typecheck --prefix integrations/photon

# Read-only checks of an already running app:
python scripts/demo_preflight.py --db /actual/CTRLF_DB_PATH
python scripts/camera_diagnostic.py --seconds 30
```

Without `KEEPSAKE_HTTP_E2E=1`, only the ephemeral-network bridge is explicitly skipped. Diagnostics never send a message or open a camera. Legacy departure GET routes are deliberately avoided because they can materialize events. `GET /api/voice` may refresh the voice list, but no synthesis is requested. `--strict` on preflight treats warnings as failures.

Review the branch against `integration/merge-all`; merge only through the team's normal approval flow. The supplied format-patch applies the QA commit to this base; the incremental bundle requires base `5c3b62c` already present. Do not overwrite the team's checkout with the QA directory or reset its branch to an older base.

## Demo sequence and remaining limits

1. Run the reviewed integrated commit and select the verified iPhone camera. Check preview/pixel freshness, model readiness, and a rehearsed supported object with the passive preflight.
2. Show a real object, wait for its real persisted photo, move away, then search for it. Confirm the real item/photo/time. Wearable answers deliberately avoid ungrounded room areas.
3. Use manual Voice/Find, let the question finish, and answer with the observed object. If Grok or recognition fails, use the existing browser/typed fallback. Hardware microphone/earbud behavior and actual paid Grok audio still need a human rehearsal.
4. With explicit wearer/recipient consent, the Photon owner enables both backend reminders and their authorized agent. Verify High-Assistance/Everyday mode, selected items and timing. Use the current `npm run reminder:check` only as a clearly labeled manual check; it can send a real message. Verify actual handset receipt, not just Spectrum acceptance.
5. Rehearse automatic placement/separation using genuine events separately. A worn camera losing sight is a weak signal; proximity is not contact and reminders do not establish an object was forgotten. Walking/mount/reconnect performance and detector accuracy were not physically tested here.
6. If delivery outcome is uncertain, inspect claim/result state and the recipient device before retrying. Claim revalidation cannot retract an already sent message. Turn reminders off after the authorized demo.

Roman's independent application still needs an explicit team decision and adapter before its autonomous prompt logic can be called part of this merged product. This PR verifies the current merged manual voice/retrieval flow and removes the incompatible fixed-camera trigger.
