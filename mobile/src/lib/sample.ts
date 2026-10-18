// Design-only sample data, used when EXPO_PUBLIC_SAMPLE=1. Never shown in live mode.
import type { Answer, Profile, Reminder, TrackedObject } from './api'

const min = (m: number) => new Date(Date.now() - m * 60000).toISOString()
const item = (id: string, name: string, icon: string, region: string | null, m: number | null, visible = false): TrackedObject => ({
  object_id: id,
  category: id,
  name,
  icon,
  seen: region != null,
  status: region == null ? 'never' : visible ? 'visible' : 'last_seen',
  region,
  last_seen: m == null ? null : min(m),
  visible,
  moving: false,
  snapshot: null,
})

export const objects: TrackedObject[] = [
  item('keys', 'Keys', 'keys', 'Kitchen counter', 12),
  item('glasses', 'Glasses', 'glasses', 'Bedside table', 3, true),
  item('phone', 'Phone', 'phone', 'Couch', 40),
  item('wallet', 'Wallet', 'wallet', 'Coat pocket', 180),
  item('airpods', 'AirPods', 'airpods', 'Desk', 25, true),
  item('bottle', 'Water bottle', 'bottle', 'Kitchen table', 70),
  item('bag', 'Bag', 'backpack', null, null),
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
  if (!o.region) return { found: false, answer: `I haven't seen your ${o.name.toLowerCase()} yet.`, object: o }
  const plural = o.name.endsWith('s')
  const verb = o.visible ? (plural ? 'are' : 'is') : plural ? 'were last' : 'was last'
  return { found: true, answer: `Your ${o.name.toLowerCase()} ${verb} on the ${o.region.toLowerCase()}.`, object: o }
}
