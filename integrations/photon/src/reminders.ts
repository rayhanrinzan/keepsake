// Delivers reminders that Keepsake's policy engine queued. The engine decides *whether* to remind;
// this side only checks its own recipient allowlist, formats, sends and reports the outcome.

import type { Config } from "./config.ts";
import { composeReminder } from "./format.ts";
import { type KeepsakeClient, KeepsakeRefused, KeepsakeUnavailable, type ReminderAlert } from "./keepsake.ts";
import type { Notifier, Photo } from "./notifier.ts";

type Log = (msg: string) => void;

const MAX_PHOTOS = 3;

export interface Delivery {
  alert: ReminderAlert;
  /** Spectrum accepted the send request. Not proof the phone received it. */
  accepted: number;
  failed: number;
}

export class ReminderDelivery {
  private timer: NodeJS.Timeout | undefined;
  private busy = false;
  private online: boolean | null = null;
  private warnedDisabled = false;

  constructor(
    private readonly keepsake: KeepsakeClient,
    private readonly notifier: Notifier,
    private readonly config: Config,
    private readonly log: Log = console.log,
    private readonly timeZone?: string,
  ) {}

  start() {
    const tick = async () => {
      await this.poll();
      this.timer = setTimeout(tick, this.config.pollMs);
    };
    void tick();
  }

  stop() {
    clearTimeout(this.timer);
  }

  /** One poll: deliver every queued reminder. Never throws. */
  async poll(): Promise<Delivery[]> {
    if (this.busy) return [];
    this.busy = true;
    try {
      const queued = await this.keepsake.queuedAlerts();
      this.setOnline(true);
      if (!this.config.alertsEnabled || this.config.recipients.length === 0) {
        if (queued.length && !this.warnedDisabled) {
          this.log("[reminders] reminders are queued but ALERTS_ENABLED is off here; not sending");
          this.warnedDisabled = true;
        }
        return []; // leave them: the engine expires alerts nobody delivers
      }
      const out: Delivery[] = [];
      for (const a of queued) {
        const d = await this.deliver(a);
        if (d) out.push(d);
      }
      return out;
    } catch (err) {
      if (err instanceof KeepsakeUnavailable) this.setOnline(false, err.message);
      else this.log(`[reminders] poll error: ${err instanceof Error ? err.message : String(err)}`);
      return [];
    } finally {
      this.busy = false;
    }
  }

  private async deliver(queued: ReminderAlert): Promise<Delivery | null> {
    let alert: ReminderAlert;
    try {
      alert = await this.keepsake.claim(queued.id); // exclusive: never sent twice
    } catch (err) {
      if (err instanceof KeepsakeRefused) return null; // cancelled or taken meanwhile
      throw err;
    }
    const text = composeReminder(alert, this.timeZone);
    const photos = await this.photos(alert);
    let accepted = 0;
    let failed = 0;
    let lastError = "";
    for (const to of this.config.recipients) {
      try {
        await this.notifier.send(to, text, photos);
        accepted++;
      } catch (err) {
        failed++;
        lastError = err instanceof Error ? err.message : String(err);
      }
    }
    const names = alert.items.map((i) => i.name).join(", ");
    try {
      await this.keepsake.report(alert.id, accepted ? "accepted" : "failed", lastError || undefined);
    } catch (err) {
      this.log(`[reminders] couldn't report reminder #${alert.id}: ${err instanceof Error ? err.message : err}`);
    }
    this.log(
      `[reminders] #${alert.id} (${alert.trigger}, ${alert.mode}) about ${names}: ` +
        (accepted
          ? `accepted by ${this.notifier.name} for ${accepted}/${this.config.recipients.length} recipient(s), ${photos.length} photo(s)`
          : `send failed (attempt ${alert.attempts}): ${lastError}`),
    );
    return { alert, accepted, failed };
  }

  /** The real last-seen photo of each item (max 3). A photo that can't be fetched is skipped. */
  private async photos(alert: ReminderAlert): Promise<Photo[]> {
    const out: Photo[] = [];
    for (const item of alert.items.slice(0, MAX_PHOTOS)) {
      if (item.snapshot_id == null) continue;
      try {
        out.push({ name: `${item.object_id}.jpg`, data: await this.keepsake.photo(item.snapshot_id) });
      } catch (err) {
        this.log(`[reminders] photo for ${item.name} unavailable: ${err instanceof Error ? err.message : err}`);
      }
    }
    return out;
  }

  private setOnline(online: boolean, why?: string) {
    if (this.online === online) return;
    this.online = online;
    this.log(online ? "[reminders] connected to Keepsake backend" : `[reminders] ${why}; will keep retrying`);
  }
}
