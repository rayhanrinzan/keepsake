# Running the Keepsake demo on another Mac

For moving the demo to a teammate's laptop (with their iPhone as the chest camera). About 15 minutes,
most of it downloads.

## 1. Get the code and install

```bash
git clone https://github.com/rayhanrinzan/keepsake.git ~/Projects/keepsake   # or: git pull on main
cd ~/Projects/keepsake
bash scripts/setup_mac.sh
```

The script makes `.venv`, installs the backend, web app and Photon agent, downloads the hand model, and
lists the cameras macOS sees. It never overwrites an existing `.env`.

## 2. Copy the two secret files from the current demo Mac

Send these privately (AirDrop), never through git, Slack or chat:

| File | Holds |
|---|---|
| `.env` (repo root) | `XAI_API_KEY` for the Grok voice and scene descriptions |
| `integrations/photon/.env` | Photon `PROJECT_ID`/`PROJECT_SECRET`, `ALERTS_ENABLED`, `ALERT_RECIPIENTS` |

Put them at the same paths, replacing the empty ones the script made. Then `chmod 600` both. Every phone
that should get texts must be in `ALERT_RECIPIENTS` **and** be a user on the Photon project
(added by the project owner with the Photon CLI).

## 3. Camera

Continuity Camera needs an iPhone signed into the **same Apple ID** as the Mac, with Wi-Fi and Bluetooth
on. Lock the phone on the mount: it sends black or frozen frames while unlocked or in use.

The first camera open must happen from Terminal.app so macOS can ask for permission:

```bash
cd backend && ../.venv/bin/python check_camera.py iPhone
```

## 4. Run (three Terminal windows)

```bash
cd backend && CTRLF_CAMERA_NAME=iPhone ../.venv/bin/python main.py   # part of the name check_camera.py lists
```

```bash
npm --prefix frontend run dev        # open http://127.0.0.1:5173
```

```bash
cd integrations/photon && npm run start
```

The agent should log `sending ON, N authorized recipient(s)`.

**Only one Mac may run the Photon agent at a time.** Two agents on one project both answer every text.
Stop it on the old Mac first.

## 5. Before the demo

```bash
.venv/bin/python scripts/demo_preflight.py
```

- The new Mac starts with **no memory or photos**: walk past every item once so each has a last-seen photo.
- Reminders start **off**: from the demo phone, text "high assistance" to the Keepsake line Photon
  assigned that phone (the project owner can look it up).
- Test the loop: text "where are my glasses" and expect the answer with its photo.
