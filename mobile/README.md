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

