// Synthetic Keepsake data for unit tests only (never used by the live agent).
import type { Config } from "../src/config.ts";
import type { DepartureContext, DepartureEvent, KeepsakeObject } from "../src/keepsake.ts";

export const NOW = Date.parse("2026-10-17T14:40:00Z");
export const VIEW = "view-a";

export function obj(category: string, name: string, over: Partial<KeepsakeObject> = {}): KeepsakeObject {
  return {
    object_id: `${category.replace(/ /g, "_")}_01`,
    category,
    name,
    seen: true,
    status: "last_seen",
    region: "Couch",
    last_seen: "2026-10-17T14:32:00Z",
    visible: false,
    confidence: 0.8,
    moving: false,
    awaiting_reconfirmation: false,
    lost_while_moving: false,
    ...over,
  };
}

export const never = (category: string, name: string) =>
  obj(category, name, { seen: false, status: "never", region: null, last_seen: null, confidence: null });

export function ctx(over: Partial<DepartureContext> = {}): DepartureContext {
  return {
    camera: "active",
    mode: "MONITORING",
    view_id: VIEW,
    hold: null,
    places: { keys_01: "on the couch", wallet_01: "on the desk", cell_phone_01: "near the bed" },
    ...over,
  };
}

export function event(over: Partial<DepartureEvent> = {}): DepartureEvent {
  return { id: 1, type: "possible_departure", source: "manual", at: "2026-10-17T14:39:50Z", view_id: VIEW, ...over };
}

export const POLICY = {
  enabled: true,
  paused: false,
  recipients: ["+15555550100"],
  importantCategories: ["keys", "wallet", "cell phone"],
  maxObservationAgeMs: 3 * 3600_000,
  maxEventAgeMs: 120_000,
  cooldownMs: 15 * 60_000,
};

export function config(over: Partial<Config> = {}): Config {
  return {
    projectId: "p",
    projectSecret: "s",
    keepsakeUrl: "http://127.0.0.1:8000",
    alertsEnabled: true,
    recipients: ["+15555550100"],
    importantItems: ["keys", "wallet", "phone"],
    maxObservationAgeMs: POLICY.maxObservationAgeMs,
    cooldownMs: POLICY.cooldownMs,
    maxEventAgeMs: 10 * 365 * 86400_000, // tests use fixed timestamps
    pollMs: 1000,
    stateFile: "",
    ...over,
  };
}

/** A fake fetch that serves canned JSON per path (or throws for "offline"). */
export function fakeFetch(routes: Record<string, unknown | ((init?: RequestInit) => unknown)>) {
  const calls: string[] = [];
  const impl = (async (input: string | URL | Request, init?: RequestInit) => {
    const url = new URL(String(input));
    const key = url.pathname + url.search;
    calls.push(`${init?.method ?? "GET"} ${key}`);
    const route = routes[key] ?? routes[url.pathname];
    if (route === undefined) return new Response("not found", { status: 404 });
    if (route === "offline") throw new TypeError("fetch failed");
    const body = typeof route === "function" ? (route as (i?: RequestInit) => unknown)(init) : route;
    return Response.json(body);
  }) as typeof fetch;
  return { impl, calls };
}
