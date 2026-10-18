export type ObjectStatus = 'visible' | 'last_seen' | 'never'

/** Vision event types (backend/events.py). */
export type ObservationType = 'object_observed' | 'interaction_candidate' | 'possible_pickup' | 'placement_confirmed'

/** A stored photo. The camera is worn, so a photo has a time but no room location. */
export interface Snapshot {
  id: number
  object_id: string
  event_type: ObservationType | 'first_seen'
  timestamp: string
  bbox: [number, number, number, number]
  confidence: number
  image_url: string
}

/** The one canonical object record, shared by List, detail and voice. */
export interface TrackedObject {
  object_id: string
  category: string
  name: string
  icon: string
  seen: boolean
  status: ObjectStatus
  last_seen: string | null
  visible: boolean
  confidence: number | null
  snapshot: Snapshot | null
}

/** Recent activity: one real observation event. */
export interface ActivityEvent {
  id: number
  object_id: string
  name: string
  event_type: ObservationType
  timestamp: string
  confidence: number
}

export interface Health {
  status: string
  camera: 'starting' | 'active' | 'error' | 'stopped' | 'disabled'
  error: string | null
  warning: string | null
  fps: number
  detections: { category: string; name: string; confidence: number }[]
  capture_enabled: boolean
  camera_mode?: 'wearable'
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
  objects: () => req<TrackedObject[]>('/objects'),
  snapshots: (id: string) => req<Snapshot[]>(`/objects/${id}/snapshots`),
  events: (limit = 20) => req<ActivityEvent[]>(`/events?limit=${limit}`),
  query: (text: string) => req<QueryResult>('/query', json('POST', { text })),
  clear: () => req<{ cleared: boolean }>('/memory', { method: 'DELETE' }),
  setCapture: (enabled: boolean) => req<{ capture_enabled: boolean }>('/settings', json('PUT', { capture_enabled: enabled })),
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
}
