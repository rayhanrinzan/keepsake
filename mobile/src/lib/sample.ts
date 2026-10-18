// Design-only sample data, used when EXPO_PUBLIC_SAMPLE=1. Never shown in live mode.
import type { Answer, Profile, Reminder, TrackedObject } from './api'

const min = (m: number) => new Date(Date.now() - m * 60000).toISOString()
// m = minutes since last seen, or null if never seen.
const item = (id: string, name: string, icon: string, m: number | null, visible = false): TrackedObject => ({
  object_id: id,
  category: id,
  name,
  icon,
  seen: m != null,
  status: m == null ? 'never' : visible ? 'visible' : 'last_seen',
  last_seen: m == null ? null : min(m),
  visible,
  snapshot: null,
})

export const objects: TrackedObject[] = [
  item('car_key_01', 'Keys', 'keys', 12),
  item('glasses_01', 'Glasses', 'glasses', 3, true),
  item('wallet_01', 'Wallet', 'wallet', 180),
  item('airpods_case_01', 'AirPods', 'airpods', 25, true),
  item('bottle_01', 'Water Bottle', 'bottle', 70),
  item('backpack_01', 'Backpack', 'backpack', null),
]

export const profile: Profile = {
  name: 'Margaret',
  address: '24 Elm Street, Cambridge',
  caretaker: { name: 'Sarah', relation: 'your daughter', phone: '+16175550142' },
  notes: ['You take your blue pills with breakfast.', 'Your cat is called Biscuit.'],
}

export const reminders: Reminder[] = [
  { id: '1', time: '8:00 AM', title: 'Take your morning pills', detail: 'The blue ones, with breakfast', done: true },
  { id: '2', time: '12:30 PM', title: 'Lunch with Sarah', detail: 'She is picking you up' },
  { id: '3', time: '6:00 PM', title: 'Take your evening pills' },
]

export function ask(text: string): Answer {
  const t = text.toLowerCase()
  const o = objects.find(x => t.includes(x.name.toLowerCase()) || t.includes(x.object_id))
  if (!o) return { found: false, answer: "I'm not sure which thing you mean. Could you say it again?", object: null }
  if (!o.seen) return { found: false, answer: `I haven't seen your ${o.name.toLowerCase()} yet.`, object: o }
  const plural = o.name.endsWith('s')
  return o.visible
    ? { found: true, answer: `Your ${o.name.toLowerCase()} ${plural ? 'are' : 'is'} in view right now.`, object: o }
    : { found: true, answer: `I last saw your ${o.name.toLowerCase()} ${Math.round((Date.now() - new Date(o.last_seen!).getTime()) / 60000)} minutes ago.`, object: o }
}
