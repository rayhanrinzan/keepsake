// Thin client for the local Keepsake backend (backend/main.py). Keepsake's memory is the source of
// truth: this never invents locations, it only reads what the backend has recorded.

/** The canonical object shape from `object_view()` in backend/main.py. */
export interface KeepsakeObject {
  object_id: string;
  category: string;
  name: string;
  seen: boolean;
  status: "never" | "visible" | "last_seen";
  region: string | null;
  last_seen: string | null;
  visible: boolean;
  confidence: number | null;
  moving: boolean;
  awaiting_reconfirmation: boolean;
  lost_while_moving: boolean;
}

export interface CatalogItem {
  object_id: string;
  category: string;
  name: string;
  aliases: string[];
}

export interface DepartureEvent {
  id: number;
  type: "possible_departure";
  source: "detector" | "manual";
  at: string;
  view_id: string | null;
}

export interface DepartureContext {
  camera: string | null;
  mode: string;
  view_id: string;
  /** Why the camera view can't be trusted right now (repositioning, shift…), or null. */
  hold: string | null;
  /** object_id → "on the couch" for every item with a last-seen area. */
  places: Record<string, string>;
}

export interface QueryAnswer {
  found: boolean;
  answer: string;
  object: KeepsakeObject | null;
}

export class KeepsakeUnavailable extends Error {}

export class KeepsakeClient {
  constructor(
    private readonly baseUrl: string,
    private readonly fetchImpl: typeof fetch = fetch,
    private readonly timeoutMs = 3000,
  ) {}

  private async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    let res: Response;
    try {
      res = await this.fetchImpl(this.baseUrl + path, {
        ...init,
        signal: AbortSignal.timeout(this.timeoutMs),
      });
    } catch (err) {
      throw new KeepsakeUnavailable(
        `Keepsake backend unreachable at ${this.baseUrl} (${err instanceof Error ? err.name : "error"})`,
      );
    }
    if (!res.ok) throw new KeepsakeUnavailable(`Keepsake ${path} returned HTTP ${res.status}`);
    try {
      return (await res.json()) as T;
    } catch {
      throw new KeepsakeUnavailable(`Keepsake ${path} returned invalid JSON`);
    }
  }

  health() {
    return this.request<{ status: string; camera: string; mode?: string }>("/api/health");
  }

  catalog() {
    return this.request<CatalogItem[]>("/api/catalog");
  }

  objects() {
    return this.request<KeepsakeObject[]>("/api/objects");
  }

  object(idOrName: string) {
    return this.request<KeepsakeObject>(`/api/objects/${encodeURIComponent(idOrName)}`);
  }

  query(text: string) {
    return this.request<QueryAnswer>("/api/query", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
  }

  departures(after: number) {
    return this.request<{ events: DepartureEvent[]; latest_id: number }>(
      `/api/departures?after=${after}`,
    );
  }

  departureContext() {
    return this.request<DepartureContext>("/api/departures/context");
  }

  simulateDeparture() {
    return this.request<DepartureEvent>("/api/departures/simulate", {
      method: "POST",
      headers: { "X-Keepsake-Local": "1" },
    });
  }
}

/** Resolve configured names/aliases ("phone") to catalog categories ("cell phone"). */
export function resolveImportant(
  wanted: string[],
  catalog: CatalogItem[],
): { categories: string[]; unknown: string[] } {
  const categories: string[] = [];
  const unknown: string[] = [];
  for (const w of wanted) {
    const hit = catalog.find(
      (c) =>
        c.category.toLowerCase() === w ||
        c.name.toLowerCase() === w ||
        c.object_id.toLowerCase() === w ||
        c.aliases.some((a) => a.toLowerCase() === w),
    );
    if (hit && !categories.includes(hit.category)) categories.push(hit.category);
    else if (!hit) unknown.push(w);
  }
  return { categories, unknown };
}
