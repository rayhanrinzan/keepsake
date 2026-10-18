import { ask } from './api'
import type { TrackedObject } from './api'

export type Answer = { text: string; object?: TrackedObject | null }

/** What Keepsake says back to one question: the date and time locally, everything else from the device. */
export async function answer(q: string): Promise<Answer> {
  if (/what (day|time)|today/i.test(q)) {
    const d = new Date()
    return { text: `It's ${d.toLocaleDateString(undefined, { weekday: 'long', month: 'long', day: 'numeric' })}, ${d.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })}.` }
  }
  try {
    const a = await ask(q)
    return { text: a.answer, object: a.object }
  } catch {
    return { text: "I can't reach your Keepsake right now. Try again in a moment." }
  }
}
