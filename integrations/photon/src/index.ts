import { Spectrum } from "spectrum-ts";
import { imessage } from "@spectrum-ts/imessage";
import { ConfigError, loadConfig } from "./config.ts";
import { DepartureAlerts } from "./departures.ts";
import { replyTo, SeenMessages } from "./inbound.ts";
import { KeepsakeClient, resolveImportant } from "./keepsake.ts";
import { AlertLedger } from "./ledger.ts";
import { SpectrumIMessageNotifier } from "./notifier.ts";

// Keepsake Departure Alerts over Photon Spectrum (iMessage).
// Keepsake's backend detects possible departures and owns object memory; this agent turns them
// into reminders and answers "where is my …?" from authorized numbers.
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
const ledger = new AlertLedger(config.stateFile);

let important = { categories: [] as string[], unknown: [] as string[] };
try {
  important = resolveImportant(config.importantItems, await keepsake.catalog());
} catch (err) {
  console.error(`[photon] can't read the Keepsake catalog (${err instanceof Error ? err.message : err}).`);
  console.error("[photon] start the Keepsake backend first: cd backend && ../.venv/bin/python main.py");
  process.exit(1);
}
if (important.unknown.length) {
  console.warn(`[photon] IMPORTANT_ITEMS not in Keepsake's catalog, ignored: ${important.unknown.join(", ")}`);
}

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
const alerts = new DepartureAlerts(keepsake, notifier, ledger, config, important.categories);
alerts.start();

console.log(
  `[photon] connected to project …${config.projectId.slice(-4)}; alerts ${config.alertsEnabled ? "ON" : "OFF"}` +
    `${ledger.paused ? " (paused by user)" : ""}, ${config.recipients.length} authorized recipient(s), ` +
    `important items: ${important.categories.join(", ") || "none"}`,
);

const shutdown = async () => {
  console.log("[photon] shutting down");
  alerts.stop();
  await app.stop().catch(() => {});
  process.exit(0);
};
process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);

const seen = new SeenMessages();
const deps = { keepsake, ledger, recipients: config.recipients, enabled: config.alertsEnabled };

for await (const [space, message] of app.messages) {
  try {
    if (message.direction !== "inbound" || !seen.firstTime(message.id)) continue;
    const from = mask(message.sender?.id);
    if (message.content.type !== "text") {
      console.log(`[photon] ignored ${message.content.type} message from ${from}`);
      continue;
    }
    const reply = await replyTo(message.sender?.id, message.content.text, deps);
    if (reply === null) {
      console.log(`[photon] ignored message from unauthorized sender ${from}`);
      continue;
    }
    await space.send(reply);
    console.log(`[photon] replied to ${from}`);
  } catch (err) {
    console.error("[photon] failed to handle message:", err instanceof Error ? err.message : err);
  }
}
