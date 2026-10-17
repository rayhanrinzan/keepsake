import type { TrackedObject } from './api'

/** Pin colors on the room map: green in view now, blue last seen, amber moving or not rechecked since a scan. */
export const PIN = { live: '#22B573', past: '#3B8EF0', warn: '#F5A623' }

export function pinColor(o: TrackedObject) {
  if (o.awaiting_reconfirmation || o.moving) return PIN.warn
  return o.visible ? PIN.live : PIN.past
}
