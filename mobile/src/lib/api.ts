import * as sample from './sample'

/** Same record the web app uses (backend /api/objects). The camera is worn, so there is no room
 *  location: only when it was last seen, whether it's in view now, and its last photo. */
export interface TrackedObject {
  object_id: string
  category: string
  name: string
  icon: string
  seen: boolean
  status: 'visible' | 'last_seen' | 'never'
  last_seen: string | null
  visible: boolean
  snapshot: Snapshot | null
}

/** A stored photo: when it was taken and the item's box in it (0..1 of the frame). */
export interface Snapshot {
  id: number
  object_id: string
  event_type: string
  timestamp: string
  bbox: [number, number, number, number]
  confidence: number
  image_url: string
}

/** One real vision event, for Recent activity. */
export interface ActivityEvent {
  id: number
  object_id: string
  name: string
  event_type: string
  timestamp: string
  confidence: number
}

export interface Answer {
  found: boolean
  answer: string
  object: TrackedObject | null
  /** null when the question didn't name an item Keepsake knows. */
  category?: string | null
}

export type VoiceProvider = 'browser' | 'grok'
export interface VoiceConfig { provider: VoiceProvider; voice_id: string; speed: number }
export interface VoiceInfo extends VoiceConfig {
  grok_available: boolean
  voices: { voice_id: string; name: string }[]
}

/** What the caretaker sets up for the person: shown on Get help and read out by the assistant. */
export interface Profile {
  name: string
  address: string
  caretaker: { name: string; relation: string; phone: string } | null
  notes: string[]
}

export interface Reminder {
  id: string
  time: string
  title: string
  detail?: string
  done?: boolean
}

// Sample mode is for design work only (npm run sample). Live mode never makes anything up.
export const SAMPLE = process.env.EXPO_PUBLIC_SAMPLE === '1'
// 'same-origin': the app is served next to the API (scripts/serve_mobile.py, e.g. through a tunnel).
const API = process.env.EXPO_PUBLIC_API_URL ?? 'http://localhost:8000'
const BASE = API === 'same-origin' ? '' : API.replace(/\/$/, '')

async function get<T>(path: string): Promise<T> {
  const r = await fetch(`${BASE}${path}`)
  if (!r.ok) throw new Error(`${path} ${r.status}`)
  return r.json()
}

export const imageUrl = (path: string) => (path.startsWith('http') ? path : `${BASE}${path}`)

/** The backend's camera status (subset of /api/health), for the setup camera view. */
export interface Health {
  camera: string // 'active', 'starting', 'error', 'disabled', …
  fps: number
  warning: string | null
  error: string | null
  detections: { category: string; name: string; confidence: number }[]
  capture_enabled: boolean
  person_present?: boolean
  /** The hosted recorded demo (demo_site/): real photos from one session, no live camera. */
  demo?: boolean
  recorded?: string
}

export async function getHealth(): Promise<Health> {
  return get('/api/health')
}

export async function getObjects(): Promise<TrackedObject[]> {
  if (SAMPLE) return sample.objects
  return get('/api/objects')
}

export async function ask(text: string): Promise<Answer> {
  if (SAMPLE) return sample.ask(text)
  const r = await fetch(`${BASE}/api/query`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text }),
  })
  if (!r.ok) throw new Error(`query ${r.status}`)
  return r.json()
}

async function send<T>(method: string, path: string, body?: unknown): Promise<T> {
  const r = await fetch(`${BASE}${path}`, {
    method,
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!r.ok) {
    const b = await r.json().catch(() => null)
    throw Object.assign(new Error(b?.detail ?? `${path} ${r.status}`), { status: r.status })
  }
  return r.json()
}

/** Earlier photos of one item, newest first. */
export const getSnapshots = (id: string): Promise<Snapshot[]> => (SAMPLE ? Promise.resolve([]) : get(`/api/objects/${id}/snapshots`))
export const getEvents = (limit = 10): Promise<ActivityEvent[]> => (SAMPLE ? Promise.resolve([]) : get(`/api/events?limit=${limit}`))
/** Voice settings are kept by the backend, so the web app and this app sound the same. */
export const getVoice = (): Promise<VoiceInfo> => get('/api/voice')
export const setVoice = (v: VoiceConfig): Promise<VoiceInfo> => send('PUT', '/api/voice', v)
export const setCapture = (enabled: boolean) => send<{ capture_enabled: boolean }>('PUT', '/api/settings', { capture_enabled: enabled })
export const clearMemory = () => send<{ cleared: boolean }>('DELETE', '/api/memory')

/** Grok speech for one sentence (MP3). Throws with status 503 when there's no xAI key. */
export async function tts(text: string, voice_id: string, speed: number): Promise<Blob> {
  const r = await fetch(`${BASE}/api/tts`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text, voice_id, speed }) })
  if (!r.ok) throw Object.assign(new Error(`tts ${r.status}`), { status: r.status })
  return r.blob()
}

// The caretaker side doesn't exist yet, so in live mode these come back empty and the screens say so.
export async function getProfile(): Promise<Profile | null> {
  return SAMPLE ? sample.profile : null
}

export async function getReminders(): Promise<Reminder[]> {
  return SAMPLE ? sample.reminders : []
}

/** "Sat, Oct 18, 2:12 AM" */
export const fullTime = (iso: string) =>
  new Date(iso).toLocaleString(undefined, { weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })
export const clockTime = (iso: string) => new Date(iso).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })

/** How each photo or event came about (same wording as the web app). */
export const EVENT_LABEL: Record<string, string> = {
  first_seen: 'First noticed',
  seen: 'Seen',
  object_observed: 'Seen',
  interaction_candidate: 'Hand near it',
  possible_pickup: 'Possibly picked up',
  placement_confirmed: 'Put down',
}

/** "just now", "10 minutes ago" */
export function ago(iso: string | null) {
  if (!iso) return ''
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000)
  if (s < 60) return 'just now'
  const n = (v: number, unit: string) => `${v} ${unit}${v === 1 ? '' : 's'} ago`
  if (s < 3600) return n(Math.round(s / 60), 'minute')
  if (s < 86400) return n(Math.round(s / 3600), 'hour')
  return new Date(iso).toLocaleDateString(undefined, { weekday: 'long' })
}

export function where(o: TrackedObject) {
  if (!o.seen) return 'Not seen yet'
  return o.visible ? 'In view now' : `Last seen ${ago(o.last_seen)}`
}
