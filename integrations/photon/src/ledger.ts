// Alert bookkeeping kept on disk (.data/, git-ignored): which departures were handled, when each
// item was last included in an alert, and whether the user paused reminders. No phone numbers or
// message text are stored.

import { mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";
import type { DepartureEvent } from "./keepsake.ts";

interface State {
  handled: string[];
  lastAlerted: Record<string, number>;
  paused: boolean;
}

const MAX_HANDLED = 200;

/** Event ids restart with the backend, so the key includes the event time and view. */
export const eventKey = (e: DepartureEvent) => `${e.view_id ?? "-"}:${e.id}:${e.at}`;

export class AlertLedger {
  private state: State = { handled: [], lastAlerted: {}, paused: false };

  constructor(private readonly file?: string) {
    if (!file) return;
    try {
      const raw = JSON.parse(readFileSync(file, "utf8"));
      this.state = {
        handled: Array.isArray(raw.handled) ? raw.handled : [],
        lastAlerted: raw.lastAlerted && typeof raw.lastAlerted === "object" ? raw.lastAlerted : {},
        paused: raw.paused === true,
      };
    } catch {
      // first run or unreadable file: start fresh
    }
  }

  get paused() {
    return this.state.paused;
  }

  get lastAlerted(): Readonly<Record<string, number>> {
    return this.state.lastAlerted;
  }

  isHandled(e: DepartureEvent) {
    return this.state.handled.includes(eventKey(e));
  }

  /** Mark a departure handled (sent, skipped or failed) so it is never retried automatically. */
  markHandled(e: DepartureEvent) {
    this.state.handled = [...this.state.handled, eventKey(e)].slice(-MAX_HANDLED);
    this.save();
  }

  markAlerted(objectIds: string[], at = Date.now()) {
    for (const id of objectIds) this.state.lastAlerted[id] = at;
    this.save();
  }

  setPaused(paused: boolean) {
    this.state.paused = paused;
    this.save();
  }

  private save() {
    if (!this.file) return;
    mkdirSync(dirname(this.file), { recursive: true });
    const tmp = this.file + ".tmp";
    writeFileSync(tmp, JSON.stringify(this.state));
    renameSync(tmp, this.file);
  }
}
