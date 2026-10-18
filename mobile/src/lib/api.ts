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
  snapshot: { image_url: string; timestamp: string } | null
}

export interface Answer {
  found: boolean
  answer: string
  object: TrackedObject | null
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
const BASE = (process.env.EXPO_PUBLIC_API_URL ?? 'http://localhost:8000').replace(/\/$/, '')

async function get<T>(path: string): Promise<T> {
  const r = await fetch(`${BASE}${path}`)
  if (!r.ok) throw new Error(`${path} ${r.status}`)
  return r.json()
}

export const imageUrl = (path: string) => (path.startsWith('http') ? path : `${BASE}${path}`)

/** The backend's camera status (subset of /api/health), for the setup camera view. */
export interface Health {
  camera: string // 'active', 'starting', 'disconnected', …
  fps: number
  warning: string | null
  error: string | null
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

// The caretaker side doesn't exist yet, so in live mode these come back empty and the screens say so.
export async function getProfile(): Promise<Profile | null> {
  return SAMPLE ? sample.profile : null
}

export async function getReminders(): Promise<Reminder[]> {
  return SAMPLE ? sample.reminders : []
}

/** "just now", "10 minutes ago" */
export function ago(iso: string | null) {
  if (!iso) return ''
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000)
  if (s < 60) return 'just now'
  if (s < 3600) return `${Math.round(s / 60)} minutes ago`
  if (s < 86400) return `${Math.round(s / 3600)} hours ago`
  return new Date(iso).toLocaleDateString(undefined, { weekday: 'long' })
}

export function where(o: TrackedObject) {
  if (!o.seen) return 'Not seen yet'
  return o.visible ? 'In view now' : `Last seen ${ago(o.last_seen)}`
}
