// Departure Alerts service: polls Keepsake for possible departures, evaluates the stored memories
// of important items, and sends one combined reminder per departure through a Notifier.

import { composeAlert, evaluateDeparture, type Evaluation } from "./alerts.ts";
import type { Config } from "./config.ts";
import { type DepartureEvent, type KeepsakeClient, KeepsakeUnavailable } from "./keepsake.ts";
import type { AlertLedger } from "./ledger.ts";
import type { Notifier } from "./notifier.ts";

type Log = (msg: string) => void;

export interface Outcome {
  event: DepartureEvent;
  evaluation: Evaluation;
  delivered: number;
  failed: number;
}

export class DepartureAlerts {
  private cursor: number | null = null;
  private online: boolean | null = null;
  private timer: NodeJS.Timeout | undefined;
  private busy = false;

  constructor(
    private readonly keepsake: KeepsakeClient,
    private readonly notifier: Notifier,
    private readonly ledger: AlertLedger,
    private readonly config: Config,
    private readonly importantCategories: string[],
    private readonly log: Log = console.log,
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

  /** One poll: fetch new departure events and handle each. Never throws. */
  async poll(): Promise<Outcome[]> {
    if (this.busy) return [];
    this.busy = true;
    try {
      const { events, latest_id } = await this.keepsake.departures(this.cursor ?? 0);
      this.setOnline(true);
      if (this.cursor === null || latest_id < this.cursor) {
        // First contact (or the backend restarted): only react to departures from now on.
        this.cursor = latest_id;
        return [];
      }
      const outcomes: Outcome[] = [];
      for (const ev of events) {
        this.cursor = Math.max(this.cursor, ev.id);
        if (this.ledger.isHandled(ev)) continue;
        outcomes.push(await this.handle(ev));
      }
      return outcomes;
    } catch (err) {
      if (err instanceof KeepsakeUnavailable) this.setOnline(false, err.message);
      else this.log(`[alerts] poll error: ${err instanceof Error ? err.message : String(err)}`);
      return [];
    } finally {
      this.busy = false;
    }
  }

  async handle(ev: DepartureEvent): Promise<Outcome> {
    const [objects, context] = await Promise.all([
      this.keepsake.objects(),
      this.keepsake.departureContext(),
    ]);
    const evaluation = evaluateDeparture(
      ev,
      objects,
      context,
      {
        enabled: this.config.alertsEnabled,
        paused: this.ledger.paused,
        recipients: this.config.recipients,
        importantCategories: this.importantCategories,
        maxObservationAgeMs: this.config.maxObservationAgeMs,
        maxEventAgeMs: this.config.maxEventAgeMs,
        cooldownMs: this.config.cooldownMs,
      },
      this.ledger.lastAlerted,
    );
    this.ledger.markHandled(ev); // handled once, whatever happens below: no automatic retries
    const skipped = evaluation.skipped.map((s) => `${s.name}=${s.reason}`).join(", ") || "none";
    if (!evaluation.send) {
      this.log(`[alerts] departure #${ev.id} (${ev.source}): no alert sent (${evaluation.blocked}); skipped: ${skipped}`);
      return { event: ev, evaluation, delivered: 0, failed: 0 };
    }
    const text = composeAlert(evaluation.items);
    let delivered = 0;
    let failed = 0;
    for (const to of this.config.recipients) {
      try {
        await this.notifier.send(to, text);
        delivered++;
      } catch (err) {
        failed++;
        this.log(`[alerts] ${this.notifier.name} send failed: ${err instanceof Error ? err.message : String(err)}`);
      }
    }
    if (delivered) this.ledger.markAlerted(evaluation.items.map((i) => i.objectId));
    this.log(
      `[alerts] departure #${ev.id} (${ev.source}): alert about ${evaluation.items.map((i) => i.name).join(", ")} ` +
        `sent to ${delivered}/${this.config.recipients.length} recipient(s); skipped: ${skipped}`,
    );
    return { event: ev, evaluation, delivered, failed };
  }

  private setOnline(online: boolean, why?: string) {
    if (this.online === online) return;
    this.online = online;
    this.log(online ? "[alerts] connected to Keepsake backend" : `[alerts] ${why}; will keep retrying`);
  }
}
