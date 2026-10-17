import { Backpack, BookOpen, Coffee, Glasses, Headphones, KeyRound, Laptop, Milk, Mouse, Package, Smartphone, Tv, Wallet } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import type { TrackedObject } from './api'

const ICONS: Record<string, LucideIcon> = {
  phone: Smartphone,
  bottle: Milk,
  laptop: Laptop,
  cup: Coffee,
  book: BookOpen,
  backpack: Backpack,
  remote: Tv,
  mouse: Mouse,
  keys: KeyRound,
  airpods: Headphones,
  wallet: Wallet,
  glasses: Glasses,
}

export const iconFor = (icon: string): LucideIcon => ICONS[icon] ?? Package

export function timeAgo(iso: string, now = Date.now()): string {
  const s = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000))
  if (s < 10) return 'just now'
  if (s < 60) return `${s} seconds ago`
  const m = Math.round(s / 60)
  if (m < 60) return m === 1 ? '1 minute ago' : `${m} minutes ago`
  const h = Math.round(m / 60)
  if (h < 24) return h === 1 ? '1 hour ago' : `${h} hours ago`
  const d = Math.round(h / 24)
  return d === 1 ? 'yesterday' : `${d} days ago`
}

export const clockTime = (iso: string) =>
  new Date(iso).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })

export const fullTime = (iso: string) =>
  new Date(iso).toLocaleString(undefined, {
    weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
  })

/** Display form of a location label from the backend ("Couch", "Near Couch", "Left side"). */
export function placeName(label: string) {
  if (label === 'Left side' || label === 'Right side') return `${label} of the room`
  if (label === 'Middle') return 'Middle of the room'
  if (label.startsWith('Near ')) return `Near the ${label.slice(5).toLowerCase()}`
  return label
}

/** Short human status used on cards and the detail view. */
export function statusLabel(o: TrackedObject): { label: string; tone: 'live' | 'past' | 'none' | 'warn' } {
  if (o.status === 'never') return { label: 'Not yet seen', tone: 'none' }
  if (o.awaiting_reconfirmation) return { label: 'Not rechecked since scan', tone: 'warn' }
  if (o.moving) return { label: 'Being moved', tone: 'warn' }
  if (o.visible) return { label: 'In view now', tone: 'live' }
  return { label: 'Out of view', tone: 'past' }
}

/** Center a thumbnail crop on the object so it stays in frame. */
export function focusPosition(bbox: [number, number, number, number] | undefined) {
  if (!bbox) return '50% 50%'
  return `${((bbox[0] + bbox[2]) / 2) * 100}% ${((bbox[1] + bbox[3]) / 2) * 100}%`
}

export const EVENT_LABEL: Record<string, string> = {
  first_seen: 'First noticed',
  moved: 'Moved here',
  moved_within: 'Shifted position',
  reconfirmed: 'Found again after camera moved',
  object_observed: 'Seen',
  placement_confirmed: 'Put down here',
}
