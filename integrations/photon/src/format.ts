// Reminder wording. Gentle, short, and only as certain as the evidence: "last seen", never
// "you forgot". A wearable can't see pockets or bags, and a reminder is not an emergency alert.

import type { ReminderAlert, ReminderItem } from "./keepsake.ts";

const clock = (iso: string, timeZone?: string) =>
  new Date(iso).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", timeZone });

const plural = (name: string) => /s$/i.test(name);
const noun = (name: string) => (name === "AirPods" ? name : name.toLowerCase());

function join(parts: string[]): string {
  if (parts.length <= 1) return parts.join("");
  return parts.slice(0, -1).join(", ") + (parts.length > 2 ? "," : "") + " and " + parts.at(-1);
}

export function composeReminder(alert: ReminderAlert, timeZone?: string): string {
  const items = alert.items;
  const opener = alert.tone === "heading_out" ? "Heading out?" : "Keepsake reminder:";
  const [one] = items;
  if (items.length === 1 && one) {
    const where = one.place ? ` ${one.place}` : "";
    const it = plural(one.name) ? "them" : "it";
    const verb = plural(one.name) ? "were" : "was";
    const photo = one.place ? "" : " The last photo is in Keepsake.";
    return `${opener} Your ${noun(one.name)} ${verb} last seen${where} at ${clock(one.last_seen, timeZone)}. Check whether you have ${it}.${photo}`;
  }
  const parts = items.map(
    (i: ReminderItem) => `${noun(i.name)} (${i.place ? `${i.place}, ` : ""}${clock(i.last_seen, timeZone)})`,
  );
  const photo = items.every((i) => i.place) ? "" : " Last photos are in Keepsake.";
  return `${opener} Keepsake last saw your ${join(parts)}. Check whether you have them.${photo}`;
}
