export type ObjectStatus = 'visible' | 'last_seen' | 'never'
export type Mode = 'MONITORING' | 'REPOSITIONING' | 'CALIBRATING' | 'READY_TO_RESUME'

export interface Snapshot {
  id: number
  object_id: string
  event_type: 'first_seen' | 'moved' | 'moved_within' | 'reconfirmed' | 'object_observed' | 'placement_confirmed'
  timestamp: string
  region: string
  bbox: [number, number, number, number]
  confidence: number
  view_id: string | null
  image_url: string
}

/** The one canonical object record, shared by List, Map, detail and voice. */
export interface TrackedObject {
  object_id: string
  category: string
  name: string
  icon: string
  seen: boolean
  status: ObjectStatus
  region: string | null
  x: number | null
  y: number | null
  last_seen: string | null
  visible: boolean
  confidence: number | null
  moving: boolean
  awaiting_reconfirmation: boolean
  lost_while_moving: boolean
  snapshot: Snapshot | null
}

export interface MoveEvent {
  id: number
  object_id: string
  name: string
  from_region: string | null
  to_region: string
  timestamp: string
  event_type: 'first_seen' | 'moved' | 'moved_within'
}

export interface Region {
  name: string
  x0: number
  y0: number
  x1: number
  y1: number
  kind: string
}

export interface ProposedArea {
  name: string
  kind: string
  camera: [number, number, number, number]
  confidence: number
}

export interface Health {
  status: string
  camera: 'starting' | 'active' | 'error' | 'stopped' | 'disabled'
  error: string | null
  warning: string | null
  fps: number
  detections: { category: string; name: string; confidence: number }[]
  mode: Mode
  reference_ready: boolean
  proposal: ProposedArea[]
  view_id: string
  capture_enabled: boolean
  person_present?: boolean
  person_left_count?: number
  /** Only set by the design-only sample server (`npm run dev:sample`). */
  sample?: boolean
}

export interface QueryResult {
  found: boolean
  answer: string
  object: TrackedObject | null
  /** null when the question didn't name an item Keepsake knows. */
  category?: string | null
}

export type VoiceProvider = 'browser' | 'grok'

export interface VoiceConfig {
  provider: VoiceProvider
  voice_id: string
  speed: number
}

export interface VoiceInfo extends VoiceConfig {
  grok_available: boolean
  voices: { voice_id: string; name: string }[]
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(`/api${path}`, init)
  } catch {
    throw new ApiError(0, "Can't reach Keepsake. Is the backend running?")
  }
  if (!res.ok) {
    const body = await res.json().catch(() => null)
    throw new ApiError(res.status, body?.detail ?? `Request failed (${res.status})`)
  }
  return res.json() as Promise<T>
}

const json = (method: string, body?: unknown): RequestInit => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: body === undefined ? undefined : JSON.stringify(body),
})

export const api = {
  health: () => req<Health>('/health'),
  regions: () => req<Region[]>('/regions'),
  objects: () => req<TrackedObject[]>('/objects'),
  snapshots: (id: string) => req<Snapshot[]>(`/objects/${id}/snapshots`),
  events: (limit = 20) => req<MoveEvent[]>(`/events?limit=${limit}`),
  query: (text: string) => req<QueryResult>('/query', json('POST', { text })),
  clear: () => req<{ cleared: boolean }>('/memory', { method: 'DELETE' }),
  setCapture: (enabled: boolean) => req<{ capture_enabled: boolean }>('/settings', json('PUT', { capture_enabled: enabled })),
  reposition: (step: 'start' | 'cancel' | 'finish' | 'resume') => req<{ mode: Mode }>(`/reposition/${step}`, json('POST')),
  saveRegions: (regions: { name: string; kind: string; camera: number[] }[]) =>
    req<Region[]>('/regions', json('PUT', { regions })),
  voice: () => req<VoiceInfo>('/voice'),
  setVoice: (v: VoiceConfig) => req<VoiceInfo>('/voice', json('PUT', v)),
  /** Grok speech for one sentence, as an MP3 blob. Throws ApiError (503 no key, 502 Grok failed). */
  tts: async (text: string, opts: { voice_id?: string; speed?: number } = {}) => {
    let res: Response
    try {
      res = await fetch('/api/tts', json('POST', { text, ...opts }))
    } catch {
      throw new ApiError(0, "Can't reach Keepsake. Is the backend running?")
    }
    if (!res.ok) {
      const body = await res.json().catch(() => null)
      throw new ApiError(res.status, body?.detail ?? `Speech failed (${res.status})`)
    }
    return res.blob()
  },
  cameraUrl: '/api/camera',
  frameUrl: '/api/camera/frame',
  referenceUrl: '/api/calibration/reference',
}
