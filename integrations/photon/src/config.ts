// Agent configuration from environment variables (.env, git-ignored). See .env.example.

export interface Config {
  projectId: string;
  projectSecret: string;
  keepsakeUrl: string;
  /**
   * Photon-side master switch, off by default. Reminders also need the backend's own opt-in
   * (mode high_assistance/everyday); both must be on before anything is sent.
   */
  alertsEnabled: boolean;
  /** E.164 numbers allowed to receive reminders and text commands. Kept only on this side. */
  recipients: string[];
  pollMs: number;
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

  return {
    projectId,
    projectSecret,
    keepsakeUrl,
    alertsEnabled,
    recipients,
    pollMs: num(env, "REMINDER_POLL_SECONDS", 2) * 1000,
  };
}
