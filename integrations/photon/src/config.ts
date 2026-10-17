// Agent configuration from environment variables (.env, git-ignored). See .env.example.

export interface Config {
  projectId: string;
  projectSecret: string;
  keepsakeUrl: string;
  /** Master switch: off by default; nothing about Keepsake memory leaves the machine until set. */
  alertsEnabled: boolean;
  /** E.164 numbers allowed to receive alerts and ask questions. */
  recipients: string[];
  /** Catalog categories, names or aliases ("keys", "wallet", "phone"). */
  importantItems: string[];
  maxObservationAgeMs: number;
  cooldownMs: number;
  maxEventAgeMs: number;
  pollMs: number;
  stateFile: string;
}

export class ConfigError extends Error {}

const E164 = /^\+[1-9]\d{7,14}$/;

const LOOPBACK = new Set(["127.0.0.1", "localhost", "[::1]", "::1"]);

function num(env: NodeJS.ProcessEnv, key: string, fallback: number): number {
  const raw = env[key];
  if (raw === undefined || raw === "") return fallback;
  const n = Number(raw);
  if (!Number.isFinite(n) || n <= 0) throw new ConfigError(`${key} must be a positive number`);
  return n;
}

export function normalizePhone(raw: string): string {
  const trimmed = raw.trim();
  return trimmed.startsWith("+") ? "+" + trimmed.slice(1).replace(/\D/g, "") : trimmed;
}

export function loadConfig(env: NodeJS.ProcessEnv = process.env): Config {
  const projectId = env.PROJECT_ID;
  const projectSecret = env.PROJECT_SECRET;
  if (!projectId || !projectSecret) {
    throw new ConfigError("PROJECT_ID and PROJECT_SECRET must be set (see .env.example)");
  }

  const keepsakeUrl = (env.KEEPSAKE_API_URL || "http://127.0.0.1:8000").replace(/\/+$/, "");
  let host: string;
  try {
    host = new URL(keepsakeUrl).hostname;
  } catch {
    throw new ConfigError("KEEPSAKE_API_URL is not a valid URL");
  }
  if (!LOOPBACK.has(host)) {
    throw new ConfigError("KEEPSAKE_API_URL must point at this machine (Keepsake is local-only)");
  }

  const recipients = (env.ALERT_RECIPIENTS || "")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean)
    .map(normalizePhone);
  const bad = recipients.filter((r) => !E164.test(r));
  if (bad.length) throw new ConfigError("ALERT_RECIPIENTS must be comma-separated E.164 numbers");

  const alertsEnabled = /^(1|true|yes|on)$/i.test(env.ALERTS_ENABLED || "");
  if (alertsEnabled && recipients.length === 0) {
    throw new ConfigError("ALERTS_ENABLED is on but ALERT_RECIPIENTS is empty");
  }

  const importantItems = (env.IMPORTANT_ITEMS || "keys,wallet,phone")
    .split(",")
    .map((s) => s.trim().toLowerCase())
    .filter(Boolean);

  return {
    projectId,
    projectSecret,
    keepsakeUrl,
    alertsEnabled,
    recipients,
    importantItems,
    maxObservationAgeMs: num(env, "ALERT_MAX_AGE_MINUTES", 180) * 60_000,
    cooldownMs: num(env, "ALERT_COOLDOWN_MINUTES", 15) * 60_000,
    maxEventAgeMs: num(env, "DEPARTURE_MAX_EVENT_AGE_SECONDS", 120) * 1000,
    pollMs: num(env, "DEPARTURE_POLL_SECONDS", 2) * 1000,
    stateFile: env.ALERT_STATE_FILE || new URL("../.data/state.json", import.meta.url).pathname,
  };
}
