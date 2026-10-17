// Replies to inbound iMessages from authorized recipients only. Simple, deterministic commands
// update Keepsake's reminder engine; "where is my …" uses Keepsake's own grounded /api/query.

import { normalizePhone } from "./config.ts";
import { type KeepsakeClient, KeepsakeRefused, KeepsakeUnavailable, type Mode } from "./keepsake.ts";

export interface InboundDeps {
  keepsake: KeepsakeClient;
  recipients: string[];
  enabled: boolean;
}

const HELP =
  'Text "high assistance", "everyday" or "reminders off" to choose a mode; "I have it", "remind me later", ' +
  '"pause reminders", "resume reminders", "heading out", or ask "where are my keys?". ' +
  "Keepsake only knows where its camera last saw things.";

const MODE_NAMES: Record<Mode, string> = {
  off: "off",
  high_assistance: "High-Assistance",
  everyday: "Everyday",
};

const is = (t: string, re: RegExp) => re.test(t);

/** The reply for one inbound text, or null to stay silent (unauthorized sender). */
export async function replyTo(sender: string | undefined, text: string, deps: InboundDeps): Promise<string | null> {
  if (!sender || !deps.recipients.includes(normalizePhone(sender))) return null;
  const t = text.trim().toLowerCase().replace(/[.!?]+$/, "");
  if (t === "ping" || t === "hello photon") return "Photon Spectrum is connected to Keepsake.";
  if (!deps.enabled) return "Keepsake text reminders are turned off on this Mac (ALERTS_ENABLED).";
  const k = deps.keepsake;
  try {
    if (is(t, /^(help|\?|commands)$/)) return HELP;
    // Mode changes: an authorized recipient texting a mode is an explicit opt-in.
    const mode: Mode | null = is(t, /^(reminders? )?(high[- ]?assistance|high)( mode)?$/)
      ? "high_assistance"
      : is(t, /^(reminders? )?every ?day( mode)?$/)
        ? "everyday"
        : is(t, /^(reminders? off|turn off reminders|stop all reminders)$/)
          ? "off"
          : null;
    if (mode) {
      await k.setReminders(mode === "off" ? { mode } : { mode, enabled: true, opt_in: true });
      return mode === "off"
        ? 'Reminders are off. Text "high assistance" or "everyday" to turn them back on.'
        : `${MODE_NAMES[mode]} reminders are on. These are gentle check-ins based on what Keepsake last saw, not emergency alerts.`;
    }
    if (is(t, /\b(pause|mute|stop)\b.*\b(reminders?|alerts?)\b/)) {
      await k.acknowledge("pause");
      return 'Reminders paused. Text "resume reminders" to turn them back on.';
    }
    if (is(t, /\b(resume|unpause|unmute)\b.*\b(reminders?|alerts?)\b/)) {
      await k.acknowledge("resume");
      return "Reminders are back on.";
    }
    if (is(t, /^(i (have|got) (it|them|everything)|got (it|them)|yes|yep|all good)$/)) {
      const r = await k.acknowledge("have_it");
      return r.ok ? "Great, thanks for checking." : "Thanks! There's no recent reminder to dismiss.";
    }
    if (is(t, /^(remind me later|later|snooze)$/)) {
      const r = await k.acknowledge("snooze");
      return r.ok ? "OK, I'll check in once more a bit later." : "There's no recent reminder to snooze.";
    }
    if (is(t, /^(i'?m |i am )?(heading out|leaving|going out)( now)?$/)) {
      const r = await k.check("heading_out");
      if (r.queued) return null; // the reminder itself is the answer
      return r.blocked === "reminders_off"
        ? 'Reminders are off. Text "everyday" or "high assistance" to turn them on.'
        : r.blocked === "paused"
          ? "Reminders are paused right now."
          : "Nothing to check: Keepsake has no recent photo of your important items.";
    }
    return (await k.query(text)).answer;
  } catch (err) {
    if (err instanceof KeepsakeUnavailable) return "Keepsake isn't reachable right now, so I can't check.";
    if (err instanceof KeepsakeRefused) return "Keepsake couldn't do that right now.";
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
