import { Spectrum } from "spectrum-ts";
import { imessage } from "@spectrum-ts/imessage";

// Keepsake ↔ Photon Spectrum bridge. For now this is the connectivity check:
// it replies to every inbound iMessage text. Departure alerts build on this.
// Docs: https://photon.codes/docs/spectrum-ts

try {
  process.loadEnvFile(new URL("../.env", import.meta.url));
} catch {
  // No .env file: fall back to variables already in the environment.
}

const projectId = process.env.PROJECT_ID;
const projectSecret = process.env.PROJECT_SECRET;
if (!projectId || !projectSecret) {
  console.error("[photon] PROJECT_ID and PROJECT_SECRET must be set (see .env.example).");
  process.exit(1);
}

// Mask phone numbers / handles in logs: keep only the last 4 characters.
const mask = (id: string | undefined) => (id ? `…${id.slice(-4)}` : "unknown");

let app: Awaited<ReturnType<typeof Spectrum>>;
try {
  app = await Spectrum({
    projectId,
    projectSecret,
    providers: [imessage.config()],
  });
} catch (err) {
  console.error("[photon] failed to connect to Spectrum:", err instanceof Error ? err.message : err);
  process.exit(1);
}

console.log(`[photon] connected to project …${projectId.slice(-4)}; waiting for iMessages`);

const shutdown = async () => {
  console.log("[photon] shutting down");
  await app.stop().catch(() => {});
  process.exit(0);
};
process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);

for await (const [space, message] of app.messages) {
  try {
    if (message.direction !== "inbound") continue;
    const from = mask(message.sender?.id);
    if (message.content.type !== "text") {
      console.log(`[photon] ignored ${message.content.type} message from ${from}`);
      continue;
    }
    const text = message.content.text;
    console.log(`[photon] inbound text from ${from} (${text.length} chars)`);
    await space.send(`Photon Spectrum is connected. You said: ${text}`);
    console.log(`[photon] reply sent to ${from}`);
  } catch (err) {
    console.error("[photon] failed to handle message:", err instanceof Error ? err.message : err);
  }
}
