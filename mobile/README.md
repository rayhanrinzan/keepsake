# Keepsake mobile

The app the person wearing Keepsake uses: talk to it, find their things, get help, see today's reminders.
Expo (React Native), so it runs on a phone with Expo Go and in a browser.

```
cd mobile
npm install
npm run sample     # design preview with made-up data, no backend needed
npm start          # live: talks to the backend at EXPO_PUBLIC_API_URL (copy .env.example to .env)
```

Press `w` for the browser, or scan the QR code with Expo Go on your phone (same Wi-Fi).

Screens live in `src/app/` (one file per screen). Live mode reads `/api/objects` and asks `/api/query`.
Sample data (`src/lib/sample.ts`) is only used by `npm run sample`.

**Same features as the web app** (when run in a browser): Grok voices (Settings → Voice: engine, voice,
speed, preview; saved in the backend so both apps sound the same), hands-free "where are my keys" /
"where did I put my water bottle" (Settings → Hands-free), "Are you looking for something?" when an item
has been out of view 10 s, answers with the description of where the item was, the last photo with the
item boxed plus earlier photos on the item page, last-photo thumbnails, Recent activity, the camera status,
and Privacy (save photos, clear all memories). On a phone build Grok and speech recognition fall back to
the device voice and typing.

**On a phone (demo video):** build the web app next to the API and open it over HTTPS (phone browsers
only allow the microphone on HTTPS):

```bash
cd mobile && EXPO_PUBLIC_API_URL=same-origin npx expo export --platform web --output-dir ../backend/data/mobile-web
cd .. && .venv/bin/python scripts/serve_mobile.py backend/data/mobile-web   # prints ?k=KEY
cloudflared tunnel --url http://127.0.0.1:8099                             # prints https://….trycloudflare.com
```

Open `https://….trycloudflare.com/?k=KEY` on the phone. Anyone with that link can see Keepsake while it
runs, so stop both when you're done. The chest iPhone is the camera, so use a second phone for the app.

**Setting up the camera:** tap the logo for Settings, then **Setup → Show camera feed**. The live view of the
worn camera (and its status, e.g. black frames) appears above My Items. It's off by default and remembered
on the device, so turn it off again before handing the phone to someone (or for judging).

Not done yet:
- Speech to text on phones needs a development build with `expo-speech-recognition`; in Expo Go you type instead. The browser version already listens.
- The caretaker side (name, address, phone, reminders, support level) has no backend yet, so in live mode those screens say nothing has been set up.

## Talking to the backend

The app reads `/api/objects` and `/api/query` from `EXPO_PUBLIC_API_URL` (see `.env.example`). The
backend listens on `127.0.0.1` only by default, so a phone on Wi-Fi can't reach it. For a demo, start
it with `CTRLF_HOST=0.0.0.0` on a network you trust: that exposes Keepsake's memories and photos to
everyone on that network.

Keepsake's camera is worn, so items have no room location: cards show "In view now", "Last seen
4 minutes ago" or "Not seen yet", and the item screen speaks the same grounded answer as the web app.

