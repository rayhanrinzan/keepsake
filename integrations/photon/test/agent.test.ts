// Agent unit tests with mocked Keepsake and Photon (synthetic data; never live memories).
import assert from "node:assert/strict";
import { test } from "node:test";
import { type Config, ConfigError, loadConfig } from "../src/config.ts";
import { composeReminder } from "../src/format.ts";
import { replyTo, SeenMessages } from "../src/inbound.ts";
import { KeepsakeClient, KeepsakeRefused, KeepsakeUnavailable, type ReminderAlert } from "../src/keepsake.ts";
import { type Notifier, SpectrumIMessageNotifier } from "../src/notifier.ts";
import { ReminderDelivery } from "../src/reminders.ts";

const ME = "+15555550100";
const ENV = { PROJECT_ID: "p", PROJECT_SECRET: "s" };

function config(over: Partial<Config> = {}): Config {
  return { projectId: "p", projectSecret: "s", keepsakeUrl: "http://127.0.0.1:8000", alertsEnabled: true,
    recipients: [ME], pollMs: 1000, ...over };
}

function alert(over: Partial<ReminderAlert> = {}): ReminderAlert {
  return {
    id: 1, created_at: "2026-10-17T18:34:20Z", trigger: "automatic", mode: "high_assistance", tone: "gentle",
    status: "queued", attempts: 0,
    items: [{ object_id: "wallet_01", name: "Wallet", last_seen: "2026-10-17T18:34:00Z",
      photo_at: "2026-10-17T18:33:58Z", snapshot_id: 12, place: null, evidence: "object_observed" }],
    ...over,
  };
}

type Route = unknown | ((init?: RequestInit) => unknown);

/** Fake Keepsake: canned JSON per "METHOD path"; "offline" throws; {status} returns an HTTP error. */
function fakeFetch(routes: Record<string, Route>) {
  const calls: { key: string; body?: unknown; headers: Headers }[] = [];
  const impl = (async (input: string | URL | Request, init?: RequestInit) => {
    const url = new URL(String(input));
    const key = `${init?.method ?? "GET"} ${url.pathname}`;
    calls.push({ key, body: init?.body ? JSON.parse(String(init.body)) : undefined, headers: new Headers(init?.headers) });
    let route = routes[key];
    if (route === undefined) return new Response(JSON.stringify({ detail: "not found" }), { status: 404 });
    if (route === "offline") throw new TypeError("fetch failed");
    if (typeof route === "function") route = (route as (i?: RequestInit) => unknown)(init);
    if (route && typeof route === "object" && "httpStatus" in route) {
      const r = route as { httpStatus: number; detail?: string };
      return new Response(JSON.stringify({ detail: r.detail ?? "refused" }), { status: r.httpStatus });
    }
    return Response.json(route);
  }) as typeof fetch;
  return { impl, calls };
}

class FakeNotifier implements Notifier {
  name = "fake";
  sent: [string, string][] = [];
  constructor(private fail = false) {}
  async send(to: string, text: string) {
    if (this.fail) throw new Error("photon 503");
    this.sent.push([to, text]);
  }
}

const quiet = () => {};
const client = (routes: Record<string, Route>) => {
  const ff = fakeFetch(routes);
  return { k: new KeepsakeClient("http://127.0.0.1:8000", ff.impl), calls: ff.calls };
};

// ---------- config ----------

test("config: sending is off by default; recipients must be explicit E.164 numbers", () => {
  const c = loadConfig(ENV);
  assert.equal(c.alertsEnabled, false);
  assert.deepEqual(c.recipients, []);
  assert.throws(() => loadConfig({ ...ENV, ALERTS_ENABLED: "true" }), ConfigError);
  assert.deepEqual(loadConfig({ ...ENV, ALERTS_ENABLED: "1", ALERT_RECIPIENTS: " +1 (555) 555-0100 " }).recipients, [ME]);
  assert.throws(() => loadConfig({}), /PROJECT_ID/);
  assert.throws(() => loadConfig({ ...ENV, ALERT_RECIPIENTS: "5555550100" }), /E\.164/);
  assert.throws(() => loadConfig({ ...ENV, KEEPSAKE_API_URL: "https://example.com" }), /this machine/);
  assert.throws(() => loadConfig({ ...ENV, REMINDER_POLL_SECONDS: "0" }), /positive/);
});

// ---------- wording ----------

test("format: wearable reminder is grounded in time and photo, never a made-up place", () => {
  const text = composeReminder(alert(), "UTC");
  assert.equal(text, "Keepsake reminder: Your wallet was last seen at 6:34 PM. Check whether you have it. The last photo is in Keepsake.");
  assert.doesNotMatch(text, /couch|table|room|forgot|left behind|definitely/i);
});

test("format: place only when the memory supports it; Everyday tone; plurals", () => {
  const a = alert({ tone: "heading_out", mode: "everyday" });
  a.items[0] = { ...a.items[0]!, name: "Keys", place: "on the bed" };
  assert.equal(composeReminder(a, "UTC"), "Heading out? Your keys were last seen on the bed at 6:34 PM. Check whether you have them.");
});

test("format: several items in one short message", () => {
  const a = alert();
  a.items.push({ ...a.items[0]!, object_id: "keys_01", name: "Keys", last_seen: "2026-10-17T18:31:00Z" });
  assert.equal(
    composeReminder(a, "UTC"),
    "Keepsake reminder: Keepsake last saw your wallet (6:34 PM) and keys (6:31 PM). Check whether you have them. Last photos are in Keepsake.",
  );
});

// ---------- delivery ----------

const queuedRoutes = (over: Record<string, Route> = {}) => ({
  "GET /api/reminders/alerts": [alert()],
  "POST /api/reminders/alerts/1/claim": alert({ status: "sending", attempts: 1 }),
  "POST /api/reminders/alerts/1/result": (init?: RequestInit) => ({ ...alert(), status: JSON.parse(String(init?.body)).status }),
  ...over,
});

test("delivery: claims, sends to each authorized recipient and reports accepted", async () => {
  const { k, calls } = client(queuedRoutes());
  const n = new FakeNotifier();
  const d = new ReminderDelivery(k, n, config({ recipients: [ME, "+15555550101"] }), quiet, "UTC");
  const [out] = await d.poll();
  assert.equal(out?.accepted, 2);
  assert.deepEqual(n.sent.map(([to]) => to), [ME, "+15555550101"]);
  assert.match(n.sent[0]![1], /wallet was last seen at 6:34 PM/);
  assert.deepEqual(calls.map((c) => c.key), ["GET /api/reminders/alerts", "POST /api/reminders/alerts/1/claim",
    "POST /api/reminders/alerts/1/result"]);
  assert.deepEqual(calls[2]!.body, { status: "accepted" });
  assert.equal(calls[1]!.headers.get("X-Keepsake-Local"), "1");
});

test("delivery: Photon failure is reported as failed (the engine decides about one retry)", async () => {
  const { k, calls } = client(queuedRoutes());
  const [out] = await new ReminderDelivery(k, new FakeNotifier(true), config(), quiet).poll();
  assert.equal(out?.failed, 1);
  assert.deepEqual(calls.at(-1)!.body, { status: "failed", error: "photon 503" });
});

test("delivery: an alert someone else claimed or that was cancelled is skipped", async () => {
  const { k } = client(queuedRoutes({ "POST /api/reminders/alerts/1/claim": { httpStatus: 409 } }));
  const n = new FakeNotifier();
  assert.deepEqual(await new ReminderDelivery(k, n, config(), quiet).poll(), []);
  assert.equal(n.sent.length, 0);
});

test("delivery: nothing is claimed or sent when sending is off on this side", async () => {
  const { k, calls } = client(queuedRoutes());
  const n = new FakeNotifier();
  await new ReminderDelivery(k, n, config({ alertsEnabled: false }), quiet).poll();
  assert.equal(n.sent.length, 0);
  assert.deepEqual(calls.map((c) => c.key), ["GET /api/reminders/alerts"]);
});

test("delivery: backend offline never throws and recovers", async () => {
  const routes: Record<string, Route> = { "GET /api/reminders/alerts": "offline" };
  const { k } = client(routes);
  const logs: string[] = [];
  const d = new ReminderDelivery(k, new FakeNotifier(), config(), (m) => logs.push(m));
  assert.deepEqual(await d.poll(), []);
  routes["GET /api/reminders/alerts"] = [];
  assert.deepEqual(await d.poll(), []);
  assert.deepEqual(logs.map((l) => l.split(" ")[1]), ["Keepsake", "connected"]);
});

test("notifier: opens a 1:1 Spectrum space and sends; failures propagate", async () => {
  const log: string[] = [];
  await new SpectrumIMessageNotifier(async (to) => ({ send: async (t: string) => void log.push(`${to}:${t}`) }))
    .send(ME, "hi");
  assert.deepEqual(log, [`${ME}:hi`]);
  await assert.rejects(new SpectrumIMessageNotifier(async () => {
    throw new Error("unauthorized recipient");
  }).send(ME, "hi"), /unauthorized/);
});

// ---------- client ----------

test("client: 4xx is a refusal with the backend's reason; network errors are unavailable", async () => {
  const { k } = client({ "POST /api/reminders/check": { httpStatus: 409, detail: "needs opt-in" },
    "GET /api/health": "offline" });
  await assert.rejects(k.check("manual"), (e) => e instanceof KeepsakeRefused && /needs opt-in/.test(e.message));
  await assert.rejects(k.health(), KeepsakeUnavailable);
  const bad = new KeepsakeClient("http://127.0.0.1:8000", (async () => new Response("<html>")) as typeof fetch);
  await assert.rejects(bad.health(), /invalid JSON/);
});

// ---------- inbound ----------

const inbound = (routes: Record<string, Route>, enabled = true) => {
  const { k, calls } = client(routes);
  return { deps: { keepsake: k, recipients: [ME], enabled }, calls };
};

test("inbound: unauthorized senders get nothing and nothing changes", async () => {
  const { deps, calls } = inbound({});
  assert.equal(await replyTo("+15555550199", "reminders off", deps), null);
  assert.equal(await replyTo(undefined, "hi", deps), null);
  assert.equal(calls.length, 0);
});

test("inbound: texting a mode is an explicit opt-in; off turns it off", async () => {
  const { deps, calls } = inbound({ "PUT /api/reminders/settings": { active: true } });
  assert.match((await replyTo(ME, "High assistance", deps))!, /High-Assistance reminders are on.*not emergency/);
  assert.deepEqual(calls[0]!.body, { mode: "high_assistance", enabled: true, opt_in: true });
  assert.match((await replyTo(ME, "everyday", deps))!, /Everyday/);
  assert.match((await replyTo(ME, "Reminders off", deps))!, /off/);
  assert.deepEqual(calls[2]!.body, { mode: "off" });
});

test("inbound: I have it / remind me later / pause / resume map to the engine", async () => {
  const { deps, calls } = inbound({ "POST /api/reminders/ack": (init?: RequestInit) => ({ ok: true,
    action: JSON.parse(String(init?.body)).action }) });
  assert.match((await replyTo(ME, "I have it!", deps))!, /thanks/i);
  assert.match((await replyTo(ME, "remind me later", deps))!, /later/);
  assert.match((await replyTo(ME, "pause reminders", deps))!, /paused/);
  assert.match((await replyTo(ME, "resume reminders", deps))!, /back on/);
  assert.deepEqual(calls.map((c) => (c.body as { action: string }).action), ["have_it", "snooze", "pause", "resume"]);
});

test("inbound: heading out runs a real check; the reminder is the reply", async () => {
  const { deps, calls } = inbound({ "POST /api/reminders/check": { queued: true, alert: alert(), skipped: [] } });
  assert.equal(await replyTo(ME, "I'm heading out", deps), null);
  assert.deepEqual(calls[0]!.body, { reason: "heading_out" });
  const off = inbound({ "POST /api/reminders/check": { queued: false, blocked: "reminders_off", skipped: [] } });
  assert.match((await replyTo(ME, "leaving", off.deps))!, /Reminders are off/);
});

test("inbound: questions use Keepsake's own answer; offline and disabled are explained", async () => {
  const { deps } = inbound({ "POST /api/query": { found: true, answer: "I last saw your keys 5 minutes ago." } });
  assert.equal(await replyTo(ME, "Where are my keys?", deps), "I last saw your keys 5 minutes ago.");
  const offline = inbound({ "POST /api/query": "offline" });
  assert.match((await replyTo(ME, "where is my wallet", offline.deps))!, /isn't reachable/);
  const disabled = inbound({}, false);
  assert.match((await replyTo(ME, "where is my wallet", disabled.deps))!, /turned off/);
  assert.match((await replyTo(ME, "Hello Photon", disabled.deps))!, /connected/);
});

test("inbound: the same message id is processed once", () => {
  const seen = new SeenMessages(2);
  assert.equal(seen.firstTime("a"), true);
  assert.equal(seen.firstTime("a"), false);
  seen.firstTime("b");
  seen.firstTime("c");
  assert.equal(seen.firstTime("a"), true);
});
