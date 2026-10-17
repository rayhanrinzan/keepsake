// Replies to inbound iMessages from authorized recipients: pause/resume reminders, acknowledge an
// alert, or ask where an item is (answered by Keepsake's own deterministic /api/query).

import { normalizePhone } from "./config.ts";
import { type KeepsakeClient, KeepsakeUnavailable } from "./keepsake.ts";
import type { AlertLedger } from "./ledger.ts";

export interface InboundDeps {
  keepsake: KeepsakeClient;
  ledger: AlertLedger;
  recipients: string[];
  enabled: boolean;
}

const HELP =
  'Ask "where are my keys?", or say "pause reminders" / "resume reminders". Keepsake only knows where its camera last saw things.';

/** The reply for one inbound text, or null to stay silent (unauthorized sender). */
export async function replyTo(
  sender: string | undefined,
  text: string,
  deps: InboundDeps,
): Promise<string | null> {
  if (!sender || !deps.recipients.includes(normalizePhone(sender))) return null;
  const t = text.trim().toLowerCase().replace(/[.!?]+$/, "");
  if (t === "ping" || t === "hello photon") return "Photon Spectrum is connected to Keepsake.";
  if (!deps.enabled) return "Keepsake messaging is turned off (ALERTS_ENABLED).";
  if (/^(help|\?)$/.test(t)) return HELP;
  if (/\b(pause|stop|mute)\b.*\b(reminders?|alerts?)\b/.test(t)) {
    deps.ledger.setPaused(true);
    return 'Departure reminders paused. Text "resume reminders" to turn them back on.';
  }
  if (/\b(resume|start|unmute)\b.*\b(reminders?|alerts?)\b/.test(t)) {
    deps.ledger.setPaused(false);
    return "Departure reminders are back on.";
  }
  if (/^(i (have|got) (them|it|everything)|got (them|it)|yes|yep|all good)$/.test(t)) {
    return "Great, have a good one!";
  }
  try {
    const r = await deps.keepsake.query(text);
    return r.answer;
  } catch (err) {
    if (err instanceof KeepsakeUnavailable) return "Keepsake isn't reachable right now, so I can't check.";
    throw err;
  }
}

/** Remembers recent inbound message ids so a redelivered message is processed once. */
export class SeenMessages {
  private ids: string[] = [];
  constructor(private readonly max = 500) {}
  firstTime(id: string): boolean {
    if (this.ids.includes(id)) return false;
    this.ids.push(id);
    if (this.ids.length > this.max) this.ids.shift();
    return true;
  }
}
