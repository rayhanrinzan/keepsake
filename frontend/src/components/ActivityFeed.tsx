import type { ActivityEvent } from '../lib/api'
import { EVENT_LABEL, clockTime } from '../lib/format'

/** Recent real vision events. Hand events are evidence, not proof, so they're worded softly. */
export function ActivityFeed({ events }: { events: ActivityEvent[] }) {
  return (
    <section className="card px-4 py-3.5">
      <h2 className="mb-2 font-semibold">Recent activity</h2>
      {events.length === 0 ? (
        <p className="text-muted">Nothing seen yet.</p>
      ) : (
        <ul className="divide-y divide-hairline">
          {events.map((e) => (
            <li key={e.id} className="flex items-baseline justify-between gap-3 py-2 text-[14px]">
              <span className="min-w-0">
                <span className="font-medium">{e.name}</span>{' '}
                <span className="text-muted">{(EVENT_LABEL[e.event_type] ?? e.event_type).toLowerCase()}</span>
              </span>
              <time className="shrink-0 text-[13px] text-muted tabular-nums">{clockTime(e.timestamp)}</time>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
