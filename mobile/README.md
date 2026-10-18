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

Not done yet:
- Speech to text on phones needs a development build with `expo-speech-recognition`; in Expo Go you type instead. The browser version already listens.
- The caretaker side (name, address, phone, reminders, support level) has no backend yet, so in live mode those screens say nothing has been set up.
