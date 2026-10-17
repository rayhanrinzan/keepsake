import { Spectrum } from "spectrum-ts";
import { imessage } from "@spectrum-ts/imessage";
import { ConfigError, loadConfig } from "./config.ts";
import { replyTo, SeenMessages } from "./inbound.ts";
import { KeepsakeClient } from "./keepsake.ts";
import { SpectrumIMessageNotifier } from "./notifier.ts";
import { ReminderDelivery } from "./reminders.ts";

// Keepsake smart memory reminders over Photon Spectrum (iMessage).
// Keepsake's backend owns memory and decides when a reminder is due (backend/reminders.py);
// this agent delivers them to authorized numbers and handles their text replies.
// Docs: https://photon.codes/docs/spectrum-ts

try {
  process.loadEnvFile(new URL("../.env", import.meta.url));
} catch {
  // No .env file: fall back to variables already in the environment.
}

let config;
try {
  config = loadConfig();
} catch (err) {
  console.error(`[photon] config error: ${err instanceof ConfigError ? err.message : err}`);
  process.exit(1);
}

// Mask phone numbers / handles in logs: keep only the last 4 characters.
const mask = (id: string | undefined) => (id ? `…${id.slice(-4)}` : "unknown");

const keepsake = new KeepsakeClient(config.keepsakeUrl);

let app: Awaited<ReturnType<typeof Spectrum>>;
try {
  app = await Spectrum({
    projectId: config.projectId,
    projectSecret: config.projectSecret,
    providers: [imessage.config()],
  });
} catch (err) {
  console.error("[photon] failed to connect to Spectrum:", err instanceof Error ? err.message : err);
  process.exit(1);
}

const notifier = new SpectrumIMessageNotifier((to) => imessage(app).space.create(to));
const delivery = new ReminderDelivery(keepsake, notifier, config);
delivery.start();

const mode = await keepsake.reminderStatus().then(
  (s) => `${s.settings.mode}${s.active ? "" : " (not opted in)"}${s.settings.paused ? ", paused" : ""}`,
  () => "unknown (backend offline)",
);
console.log(
  `[photon] connected to project …${config.projectId.slice(-4)}; sending ${config.alertsEnabled ? "ON" : "OFF"}, ` +
    `${config.recipients.length} authorized recipient(s); Keepsake reminder mode: ${mode}`,
);

const shutdown = async () => {
  console.log("[photon] shutting down");
  delivery.stop();
  await app.stop().catch(() => {});
  process.exit(0);
};
process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);

const seen = new SeenMessages();
const deps = { keepsake, recipients: config.recipients, enabled: config.alertsEnabled };

for await (const [space, message] of app.messages) {
  try {
    if (message.direction !== "inbound" || !seen.firstTime(message.id)) continue;
    const from = mask(message.sender?.id);
    if (message.content.type !== "text") {
      console.log(`[photon] ignored ${message.content.type} message from ${from}`);
      continue;
    }
    if (!config.recipients.includes(message.sender?.id ?? "")) {
      console.log(`[photon] ignored message from unauthorized sender ${from}`);
      continue;
    }
    const reply = await replyTo(message.sender?.id, message.content.text, deps);
    if (reply === null) continue; // e.g. "heading out": the reminder itself is the reply
    await space.send(reply);
    console.log(`[photon] replied to ${from}`);
  } catch (err) {
    console.error("[photon] failed to handle message:", err instanceof Error ? err.message : err);
  }
}
