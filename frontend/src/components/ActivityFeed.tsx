import type { MoveEvent } from '../lib/api'
import { clockTime, placeName } from '../lib/format'

function describe(e: MoveEvent) {
  const to = placeName(e.to_region)
  if (e.event_type === 'first_seen' || !e.from_region) return `first seen · ${to}`
  if (e.event_type === 'moved_within') return `moved within ${to}`
  return `${placeName(e.from_region)} → ${to}`
}

export function ActivityFeed({ events }: { events: MoveEvent[] }) {
  return (
    <section className="card px-4 py-3.5">
      <h2 className="mb-2 font-semibold">Recent activity</h2>
      {events.length === 0 ? (
        <p className="text-muted">No movements recorded yet.</p>
      ) : (
        <ul className="divide-y divide-hairline">
          {events.map((e) => (
            <li key={e.id} className="flex items-baseline justify-between gap-3 py-2 text-[14px]">
              <span className="min-w-0">
                <span className="font-medium">{e.name}</span> <span className="text-muted">{describe(e)}</span>
              </span>
              <time className="shrink-0 text-[13px] text-muted tabular-nums">{clockTime(e.timestamp)}</time>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
