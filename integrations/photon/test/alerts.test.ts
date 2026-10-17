import assert from "node:assert/strict";
import { test } from "node:test";
import { composeAlert, evaluateDeparture } from "../src/alerts.ts";
import { ctx, event, never, NOW, obj, POLICY, VIEW } from "./helpers.ts";

const objects = [obj("keys", "Keys"), obj("wallet", "Wallet", { region: "Desk" }), never("cell phone", "Phone")];

test("eligible important items are combined into one alert", () => {
  const r = evaluateDeparture(event(), objects, ctx(), POLICY, {}, NOW);
  assert.equal(r.send, true);
  assert.deepEqual(r.items.map((i) => i.name), ["Keys", "Wallet"]);
  assert.deepEqual(r.skipped, [{ name: "Phone", reason: "never_seen" }]);
});

test("only configured important items are considered", () => {
  const r = evaluateDeparture(event(), [...objects, obj("laptop", "Laptop")], ctx(),
    { ...POLICY, importantCategories: ["laptop"] }, {}, NOW);
  assert.equal(r.send, false); // laptop has no place phrase in the context
  assert.deepEqual(r.skipped, [{ name: "Laptop", reason: "no_location" }]);
});

test("unsupported important item is reported, not invented", () => {
  const r = evaluateDeparture(event(), objects, ctx(), { ...POLICY, importantCategories: ["umbrella"] }, {}, NOW);
  assert.equal(r.send, false);
  assert.equal(r.blocked, "no_eligible_items");
  assert.deepEqual(r.skipped, [{ name: "umbrella", reason: "not_tracked" }]);
});

test("global gates block every alert", () => {
  const cases: [Partial<typeof POLICY>, Parameters<typeof ctx>[0], Parameters<typeof event>[0], string][] = [
    [{ enabled: false }, {}, {}, "alerts_disabled"],
    [{ paused: true }, {}, {}, "paused_by_user"],
    [{ recipients: [] }, {}, {}, "no_authorized_recipient"],
    [{}, { hold: "camera_repositioning" }, {}, "camera_repositioning"],
    [{}, { hold: "camera_shift" }, {}, "camera_shift"],
    [{}, { mode: "CALIBRATING" }, {}, "camera_repositioning"],
    [{}, { view_id: "view-b" }, {}, "camera_view_changed"],
    [{}, {}, { at: "2026-10-17T14:00:00Z" }, "event_too_old"],
  ];
  for (const [p, c, e, why] of cases) {
    const r = evaluateDeparture(event(e), objects, ctx(c), { ...POLICY, ...p }, {}, NOW);
    assert.equal(r.send, false, why);
    assert.equal(r.blocked, why);
  }
});

test("stale, uncertain and moving memories are skipped", () => {
  const items = [
    obj("keys", "Keys", { last_seen: "2026-10-17T09:00:00Z" }),
    obj("wallet", "Wallet", { awaiting_reconfirmation: true }),
    obj("cell phone", "Phone", { lost_while_moving: true }),
  ];
  const r = evaluateDeparture(event(), items, ctx(), POLICY, {}, NOW);
  assert.equal(r.send, false);
  assert.deepEqual(r.skipped.map((s) => s.reason), ["stale", "camera_repositioned", "lost_while_moving"]);
  const moving = evaluateDeparture(event(), [obj("keys", "Keys", { moving: true })], ctx(),
    { ...POLICY, importantCategories: ["keys"] }, {}, NOW);
  assert.deepEqual(moving.skipped, [{ name: "Keys", reason: "moving" }]);
});

test("cooldown suppresses an item alerted recently but not others", () => {
  const r = evaluateDeparture(event(), objects, ctx(), POLICY, { keys_01: NOW - 60_000 }, NOW);
  assert.deepEqual(r.items.map((i) => i.name), ["Wallet"]);
  assert.ok(r.skipped.some((s) => s.name === "Keys" && s.reason === "cooldown"));
  const later = evaluateDeparture(event(), objects, ctx(), POLICY, { keys_01: NOW - 16 * 60_000 }, NOW);
  assert.deepEqual(later.items.map((i) => i.name), ["Keys", "Wallet"]);
});

test("events without a view id still evaluate", () => {
  assert.equal(evaluateDeparture(event({ view_id: null }), objects, ctx(), POLICY, {}, NOW).send, true);
  assert.equal(VIEW, ctx().view_id);
});

test("alert text is hedged and grounded in the stored observation", () => {
  const one = composeAlert(
    [{ objectId: "keys_01", name: "Keys", place: "on the couch", lastSeen: new Date("2026-10-17T14:32:00Z"), visible: false }],
    "UTC",
  );
  assert.equal(
    one,
    "Heads up: your keys were last seen on the couch at 2:32 PM. Looks like you might be heading out. Did you bring them?",
  );
  const wallet = composeAlert(
    [{ objectId: "wallet_01", name: "Wallet", place: "on the desk", lastSeen: new Date("2026-10-17T10:32:00Z"), visible: true }],
    "UTC",
  );
  assert.match(wallet, /your wallet was last seen on the desk at 10:32 AM and is still in view\. .*Did you bring it\?$/);
  const many = composeAlert(
    [
      { objectId: "keys_01", name: "Keys", place: "on the couch", lastSeen: new Date("2026-10-17T14:32:00Z"), visible: false },
      { objectId: "wallet_01", name: "Wallet", place: "on the desk", lastSeen: new Date("2026-10-17T14:30:00Z"), visible: false },
      { objectId: "airpods_01", name: "AirPods", place: "near the bed", lastSeen: new Date("2026-10-17T14:20:00Z"), visible: false },
    ],
    "UTC",
  );
  assert.equal(
    many,
    "Heads up: Keepsake last saw your keys (on the couch, 2:32 PM), wallet (on the desk, 2:30 PM), and AirPods (near the bed, 2:20 PM). Looks like you might be heading out. Did you bring them?",
  );
  for (const text of [one, wallet, many]) assert.doesNotMatch(text, /forgot|you left|definitely/i);
});
