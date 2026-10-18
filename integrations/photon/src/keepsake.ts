// Thin client for the local Keepsake backend (backend/main.py). Keepsake's memory and its reminder
// engine (backend/reminders.py) are the source of truth: this never invents locations or events.

export interface CatalogItem {
  object_id: string;
  category: string;
  name: string;
  aliases: string[];
}

export interface QueryAnswer {
  found: boolean;
  answer: string;
  object?: { name: string; snapshot: { id: number } | null } | null;
}

export type Mode = "off" | "high_assistance" | "everyday";

export interface ReminderItem {
  object_id: string;
  name: string;
  /** Last time Keepsake saw it (ISO-8601). */
  last_seen: string;
  /** When its newest stored photo was taken; the photo itself stays local. */
  photo_at: string | null;
  snapshot_id: number | null;
  /** A location phrase only when the memory supports it (stationary camera); else null. */
  place: string | null;
  evidence: string;
}

export interface ReminderAlert {
  id: number;
  created_at: string;
  /** automatic (policy decided) | manual (developer trigger) | heading_out (user asked) */
  trigger: "automatic" | "manual" | "heading_out";
  mode: Exclude<Mode, "off">;
  tone: "gentle" | "heading_out";
  status: string;
  attempts: number;
  items: ReminderItem[];
}

export interface CheckResult {
  queued: boolean;
  blocked?: string;
  alert?: ReminderAlert;
  skipped: { object_id: string; reason: string }[];
}

export interface ReminderStatus {
  active: boolean;
  settings: { mode: Mode; enabled: boolean; paused: boolean; important: string[]; camera_mode: string };
}

export class KeepsakeUnavailable extends Error {}

/** The backend answered with a 4xx: the request was understood and refused. */
export class KeepsakeRefused extends Error {
  constructor(readonly status: number, message: string) {
    super(message);
  }
}

const LOCAL = { "X-Keepsake-Local": "1" };

export class KeepsakeClient {
  constructor(
    private readonly baseUrl: string,
    private readonly fetchImpl: typeof fetch = fetch,
    private readonly timeoutMs = 3000,
  ) {}

  private async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    let res: Response;
    try {
      res = await this.fetchImpl(this.baseUrl + path, { ...init, signal: AbortSignal.timeout(this.timeoutMs) });
    } catch (err) {
      throw new KeepsakeUnavailable(
        `Keepsake backend unreachable at ${this.baseUrl} (${err instanceof Error ? err.name : "error"})`,
      );
    }
    if (res.status >= 400 && res.status < 500) {
      let detail = `HTTP ${res.status}`;
      try {
        detail = ((await res.json()) as { detail?: string }).detail ?? detail;
      } catch {
        // keep the status
      }
      throw new KeepsakeRefused(res.status, `Keepsake ${path}: ${detail}`);
    }
    if (!res.ok) throw new KeepsakeUnavailable(`Keepsake ${path} returned HTTP ${res.status}`);
    try {
      return (await res.json()) as T;
    } catch {
      throw new KeepsakeUnavailable(`Keepsake ${path} returned invalid JSON`);
    }
  }

  /** Writes need the local-only header (it forces a CORS preflight for web pages). */
  private write<T>(method: "POST" | "PUT", path: string, body?: unknown) {
    return this.request<T>(path, {
      method,
      headers: { ...LOCAL, ...(body === undefined ? {} : { "Content-Type": "application/json" }) },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  }

  health() {
    return this.request<{ status: string; camera: string }>("/api/health");
  }

  catalog() {
    return this.request<CatalogItem[]>("/api/catalog");
  }

  query(text: string) {
    return this.request<QueryAnswer>("/api/query", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
  }

  reminderStatus() {
    return this.request<ReminderStatus>("/api/reminders/settings");
  }

  setReminders(changes: { mode?: Mode; enabled?: boolean; opt_in?: boolean }) {
    return this.write<ReminderStatus>("PUT", "/api/reminders/settings", changes);
  }

  /** One stored photo (JPEG bytes), by snapshot id, with the item circled. */
  async photo(snapshotId: number): Promise<Buffer> {
    let res: Response;
    try {
      res = await this.fetchImpl(`${this.baseUrl}/api/snapshots/${snapshotId}/image?highlight=1`, {
        signal: AbortSignal.timeout(this.timeoutMs),
      });
    } catch (err) {
      throw new KeepsakeUnavailable(`Keepsake photo ${snapshotId} unreachable (${err instanceof Error ? err.name : "error"})`);
    }
    if (!res.ok) throw new KeepsakeRefused(res.status, `Keepsake photo ${snapshotId}: HTTP ${res.status}`);
    return Buffer.from(await res.arrayBuffer());
  }

  queuedAlerts() {
    return this.request<ReminderAlert[]>("/api/reminders/alerts?status=queued");
  }

  claim(id: number) {
    return this.write<ReminderAlert>("POST", `/api/reminders/alerts/${id}/claim`);
  }

  report(id: number, status: "accepted" | "failed", error?: string) {
    return this.write<ReminderAlert>("POST", `/api/reminders/alerts/${id}/result`, { status, error });
  }

  check(reason: "manual" | "heading_out") {
    return this.write<CheckResult>("POST", "/api/reminders/check", { reason });
  }

  acknowledge(action: "have_it" | "snooze" | "pause" | "resume") {
    return this.write<{ ok: boolean; why?: string; paused?: boolean }>("POST", "/api/reminders/ack", { action });
  }
}
