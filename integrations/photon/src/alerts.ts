// Departure alert evaluation: which important items have a trustworthy last-seen location worth a
// reminder. Pure functions, independent of how the reminder is delivered.

import type { DepartureContext, DepartureEvent, KeepsakeObject } from "./keepsake.ts";

export interface AlertPolicy {
  enabled: boolean;
  paused: boolean;
  recipients: string[];
  importantCategories: string[];
  maxObservationAgeMs: number;
  maxEventAgeMs: number;
  cooldownMs: number;
}

export interface AlertItem {
  objectId: string;
  name: string;
  place: string;
  lastSeen: Date;
  visible: boolean;
}

export type SkipReason =
  | "not_tracked"
  | "never_seen"
  | "no_location"
  | "camera_repositioned"
  | "lost_while_moving"
  | "moving"
  | "stale"
  | "cooldown";

export interface Evaluation {
  send: boolean;
  /** Why no alert at all (set when send is false). */
  blocked?: string;
  items: AlertItem[];
  skipped: { name: string; reason: SkipReason }[];
}

/**
 * Decide whether a possible departure warrants a reminder.
 * `lastAlerted` maps object_id → when it was last included in an alert.
 */
export function evaluateDeparture(
  event: DepartureEvent,
  objects: KeepsakeObject[],
  context: DepartureContext,
  policy: AlertPolicy,
  lastAlerted: Record<string, number>,
  now: number = Date.now(),
): Evaluation {
  const none = (blocked: string): Evaluation => ({ send: false, blocked, items: [], skipped: [] });
  if (!policy.enabled) return none("alerts_disabled");
  if (policy.paused) return none("paused_by_user");
  if (policy.recipients.length === 0) return none("no_authorized_recipient");
  if (context.hold) return none(`camera_${context.hold.replace(/^camera_/, "")}`);
  if (context.mode !== "MONITORING") return none("camera_repositioning");
  if (event.view_id && event.view_id !== context.view_id) return none("camera_view_changed");
  if (now - Date.parse(event.at) > policy.maxEventAgeMs) return none("event_too_old");

  const items: AlertItem[] = [];
  const skipped: Evaluation["skipped"] = [];
  for (const category of policy.importantCategories) {
    const o = objects.find((x) => x.category === category);
    if (!o) {
      skipped.push({ name: category, reason: "not_tracked" });
      continue;
    }
    const skip = (reason: SkipReason) => skipped.push({ name: o.name, reason });
    const place = context.places[o.object_id];
    if (!o.seen || !o.last_seen) skip("never_seen");
    else if (o.awaiting_reconfirmation) skip("camera_repositioned");
    else if (o.lost_while_moving) skip("lost_while_moving"); // likely picked up: don't nag
    else if (o.moving) skip("moving");
    else if (!place) skip("no_location");
    else if (now - Date.parse(o.last_seen) > policy.maxObservationAgeMs) skip("stale");
    else if (now - (lastAlerted[o.object_id] ?? -Infinity) < policy.cooldownMs) skip("cooldown");
    else
      items.push({
        objectId: o.object_id,
        name: o.name,
        place: place!,
        lastSeen: new Date(o.last_seen),
        visible: o.visible,
      });
  }
  return items.length
    ? { send: true, items, skipped }
    : { send: false, blocked: "no_eligible_items", items, skipped };
}

const clock = (d: Date, timeZone?: string) =>
  d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", timeZone });

const plural = (name: string) => /s$/i.test(name);
const noun = (name: string) => (name === "AirPods" ? name : name.toLowerCase());

function join(parts: string[]): string {
  if (parts.length <= 1) return parts.join("");
  return parts.slice(0, -1).join(", ") + (parts.length > 2 ? "," : "") + " and " + parts.at(-1);
}

/**
 * The reminder text. Worded as a suggestion: Keepsake can't see pockets or bags and can't know
 * the person actually left, only where it last saw each item.
 */
export function composeAlert(items: AlertItem[], timeZone?: string): string {
  const [i] = items;
  if (items.length === 1 && i) {
    const verb = plural(i.name) ? "were" : "was";
    const them = plural(i.name) ? "them" : "it";
    const still = i.visible ? ` and ${plural(i.name) ? "are" : "is"} still in view` : "";
    return (
      `Heads up: your ${noun(i.name)} ${verb} last seen ${i.place} at ${clock(i.lastSeen, timeZone)}${still}. ` +
      `Looks like you might be heading out. Did you bring ${them}?`
    );
  }
  const parts = items.map((i) => `${noun(i.name)} (${i.place}, ${clock(i.lastSeen, timeZone)})`);
  return (
    `Heads up: Keepsake last saw your ${join(parts)}. ` +
    `Looks like you might be heading out. Did you bring them?`
  );
}
