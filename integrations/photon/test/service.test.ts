import assert from "node:assert/strict";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { ConfigError, loadConfig } from "../src/config.ts";
import { DepartureAlerts } from "../src/departures.ts";
import { replyTo, SeenMessages } from "../src/inbound.ts";
import { KeepsakeClient, KeepsakeUnavailable, resolveImportant } from "../src/keepsake.ts";
import { AlertLedger } from "../src/ledger.ts";
import { type Notifier, SpectrumIMessageNotifier } from "../src/notifier.ts";
import { config, ctx, event, fakeFetch, never, obj } from "./helpers.ts";

const ENV = { PROJECT_ID: "p", PROJECT_SECRET: "s" };
const CATALOG = [
  { object_id: "cell_phone_01", category: "cell phone", name: "Phone", aliases: ["phone", "iphone"] },
  { object_id: "keys_01", category: "keys", name: "Keys", aliases: ["keys", "key"] },
  { object_id: "wallet_01", category: "wallet", name: "Wallet", aliases: ["wallet"] },
];

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

function service(routes: Record<string, unknown>, notifier = new FakeNotifier(), cfg = config()) {
  const ff = fakeFetch(routes);
  const ledger = new AlertLedger();
  const svc = new DepartureAlerts(new KeepsakeClient(cfg.keepsakeUrl, ff.impl), notifier, ledger, cfg,
    ["keys", "wallet", "cell phone"], quiet);
  return { svc, ledger, notifier, ff };
}

// ---- config ----

test("config: alerts are off by default and need explicit recipients", () => {
  const c = loadConfig(ENV);
  assert.equal(c.alertsEnabled, false);
  assert.deepEqual(c.recipients, []);
  assert.deepEqual(c.importantItems, ["keys", "wallet", "phone"]);
  assert.throws(() => loadConfig({ ...ENV, ALERTS_ENABLED: "true" }), ConfigError);
  assert.deepEqual(loadConfig({ ...ENV, ALERTS_ENABLED: "1", ALERT_RECIPIENTS: " +1 (555) 555-0100 " }).recipients,
    ["+15555550100"]);
});

test("config: rejects missing credentials, bad numbers, remote backends and bad thresholds", () => {
  assert.throws(() => loadConfig({}), /PROJECT_ID/);
  assert.throws(() => loadConfig({ ...ENV, ALERT_RECIPIENTS: "5555550100" }), /E\.164/);
  assert.throws(() => loadConfig({ ...ENV, KEEPSAKE_API_URL: "https://example.com" }), /this machine/);
  assert.throws(() => loadConfig({ ...ENV, ALERT_COOLDOWN_MINUTES: "-1" }), /positive/);
});

// ---- Keepsake client ----

test("client: reads objects and answers queries from the backend", async () => {
  const ff = fakeFetch({
    "/api/objects": [obj("keys", "Keys")],
    "/api/query": (init?: RequestInit) => ({ found: true, answer: `echo ${JSON.parse(String(init?.body)).text}`, object: null }),
  });
  const k = new KeepsakeClient("http://127.0.0.1:8000", ff.impl);
  assert.equal((await k.objects())[0]?.name, "Keys");
  assert.equal((await k.query("where are my keys")).answer, "echo where are my keys");
  assert.deepEqual(ff.calls, ["GET /api/objects", "POST /api/query"]);
});

test("client: offline backend, HTTP errors and bad JSON become KeepsakeUnavailable", async () => {
  const ff = fakeFetch({ "/api/objects": "offline" });
  const k = new KeepsakeClient("http://127.0.0.1:8000", ff.impl);
  await assert.rejects(k.objects(), KeepsakeUnavailable);
  await assert.rejects(k.object("umbrella"), /HTTP 404/);
  const bad = new KeepsakeClient("http://127.0.0.1:8000", (async () => new Response("<html>")) as typeof fetch);
  await assert.rejects(bad.health(), /invalid JSON/);
});

test("client: simulated departure sends the local-only header", async () => {
  let header: string | null = null;
  const ff = fakeFetch({
    "/api/departures/simulate": (init?: RequestInit) => {
      header = new Headers(init?.headers).get("X-Keepsake-Local");
      return event();
    },
  });
  await new KeepsakeClient("http://127.0.0.1:8000", ff.impl).simulateDeparture();
  assert.equal(header, "1");
});

test("important items resolve through catalog names and aliases", () => {
  assert.deepEqual(resolveImportant(["keys", "phone", "Wallet".toLowerCase(), "umbrella"], CATALOG), {
    categories: ["keys", "cell phone", "wallet"],
    unknown: ["umbrella"],
  });
});

// ---- departure service ----

const routes = (events: unknown[], latest: number, over: Record<string, unknown> = {}) => ({
  "/api/departures": { events, latest_id: latest },
  "/api/objects": [obj("keys", "Keys"), never("wallet", "Wallet"), never("cell phone", "Phone")],
  "/api/departures/context": ctx(),
  ...over,
});

test("service: first poll only sets the cursor (no alerts for old events)", async () => {
  const { svc, notifier } = service(routes([event({ id: 1 })], 1));
  assert.deepEqual(await svc.poll(), []);
  assert.equal(notifier.sent.length, 0);
});

test("service: a new departure sends one real-memory alert to each recipient", async () => {
  const r = routes([], 0);
  const { svc, notifier } = service(r, undefined, config({ recipients: ["+15555550100", "+15555550101"] }));
  await svc.poll();
  r["/api/departures"] = { events: [event({ id: 1 })], latest_id: 1 };
  const [out] = await svc.poll();
  assert.equal(out?.delivered, 2);
  assert.equal(notifier.sent.length, 2);
  assert.match(notifier.sent[0]![1], /your keys were last seen on the couch/);
});

test("service: duplicate (replayed) departure events are handled once", async () => {
  const r = routes([], 0);
  const { svc, notifier } = service(r);
  await svc.poll();
  r["/api/departures"] = { events: [event({ id: 1 })], latest_id: 1 };
  await svc.poll();
  (svc as unknown as { cursor: number }).cursor = 0;
  await svc.poll();
  assert.equal(notifier.sent.length, 1);
});

test("service: cooldown stops a second alert about the same item", async () => {
  const r = routes([], 0);
  const { svc, notifier } = service(r);
  await svc.poll();
  r["/api/departures"] = { events: [event({ id: 1 })], latest_id: 1 };
  await svc.poll();
  r["/api/departures"] = { events: [event({ id: 2 })], latest_id: 2 };
  const [out] = await svc.poll();
  assert.equal(notifier.sent.length, 1);
  assert.equal(out?.evaluation.blocked, "no_eligible_items");
  assert.deepEqual(out?.evaluation.skipped[0], { name: "Keys", reason: "cooldown" });
});

test("service: Photon failure is logged once, not retried, and doesn't start a cooldown", async () => {
  const r = routes([], 0);
  const { svc, ledger } = service(r, new FakeNotifier(true));
  await svc.poll();
  r["/api/departures"] = { events: [event({ id: 1 })], latest_id: 1 };
  const [out] = await svc.poll();
  assert.equal(out?.failed, 1);
  assert.deepEqual(ledger.lastAlerted, {});
  assert.deepEqual(await svc.poll(), []); // same event isn't retried
});

test("service: offline backend never throws and recovers", async () => {
  const r = routes([], 0, { "/api/departures": "offline" });
  const { svc } = service(r);
  assert.deepEqual(await svc.poll(), []);
  r["/api/departures"] = { events: [], latest_id: 0 };
  assert.deepEqual(await svc.poll(), []);
});

test("service: alerts disabled means nothing is sent", async () => {
  const r = routes([], 0);
  const { svc, notifier } = service(r, undefined, config({ alertsEnabled: false }));
  await svc.poll();
  r["/api/departures"] = { events: [event({ id: 1 })], latest_id: 1 };
  const [out] = await svc.poll();
  assert.equal(out?.evaluation.blocked, "alerts_disabled");
  assert.equal(notifier.sent.length, 0);
});

test("ledger persists handled events, cooldowns and pause without numbers or text", async () => {
  const file = join(mkdtempSync(join(tmpdir(), "ledger-")), "state.json");
  const a = new AlertLedger(file);
  a.markHandled(event({ id: 7 }));
  a.markAlerted(["keys_01"], 123);
  a.setPaused(true);
  const b = new AlertLedger(file);
  assert.equal(b.isHandled(event({ id: 7 })), true);
  assert.equal(b.isHandled(event({ id: 7, at: "2026-10-18T00:00:00Z" })), false); // backend restarted
  assert.deepEqual(b.lastAlerted, { keys_01: 123 });
  assert.equal(b.paused, true);
  const { readFileSync } = await import("node:fs");
  assert.doesNotMatch(readFileSync(file, "utf8"), /\+1|Heads up/);
});

// ---- notifier ----

test("Spectrum notifier opens a 1:1 space for the recipient and sends the text", async () => {
  const log: string[] = [];
  const n = new SpectrumIMessageNotifier(async (to) => ({
    send: async (text: string) => void log.push(`${to}:${text}`),
  }));
  await n.send("+15555550100", "hi");
  assert.deepEqual(log, ["+15555550100:hi"]);
  const failing = new SpectrumIMessageNotifier(async () => {
    throw new Error("unauthorized recipient");
  });
  await assert.rejects(failing.send("+15555550100", "hi"), /unauthorized/);
});

// ---- inbound ----

test("inbound: unauthorized senders get no reply", async () => {
  const deps = { keepsake: new KeepsakeClient("http://x", fakeFetch({}).impl), ledger: new AlertLedger(),
    recipients: ["+15555550100"], enabled: true };
  assert.equal(await replyTo("+15555550199", "where are my keys", deps), null);
  assert.equal(await replyTo(undefined, "hi", deps), null);
});

test("inbound: questions use Keepsake's stored answer; commands pause and resume", async () => {
  const ff = fakeFetch({ "/api/query": { found: true, answer: "I last saw your keys on the couch 5 minutes ago.", object: null } });
  const ledger = new AlertLedger();
  const deps = { keepsake: new KeepsakeClient("http://127.0.0.1:8000", ff.impl), ledger,
    recipients: ["+15555550100"], enabled: true };
  assert.equal(await replyTo("+15555550100", "Where are my keys?", deps), "I last saw your keys on the couch 5 minutes ago.");
  assert.match((await replyTo("+15555550100", "Pause reminders", deps))!, /paused/);
  assert.equal(ledger.paused, true);
  assert.match((await replyTo("+15555550100", "resume reminders", deps))!, /back on/);
  assert.equal(ledger.paused, false);
  assert.match((await replyTo("+15555550100", "I have them!", deps))!, /Great/);
  assert.match((await replyTo("+15555550100", "Hello Photon", deps))!, /connected/);
});

test("inbound: backend offline and messaging disabled have clear replies", async () => {
  const off = { keepsake: new KeepsakeClient("http://127.0.0.1:8000", fakeFetch({ "/api/query": "offline" }).impl),
    ledger: new AlertLedger(), recipients: ["+15555550100"], enabled: true };
  assert.match((await replyTo("+15555550100", "where is my wallet", off))!, /isn't reachable/);
  assert.match((await replyTo("+15555550100", "where is my wallet", { ...off, enabled: false }))!, /turned off/);
});

test("inbound: the same message id is processed once", () => {
  const seen = new SeenMessages(2);
  assert.equal(seen.firstTime("a"), true);
  assert.equal(seen.firstTime("a"), false);
  seen.firstTime("b");
  seen.firstTime("c");
  assert.equal(seen.firstTime("a"), true); // evicted
});
