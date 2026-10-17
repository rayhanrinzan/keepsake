import type { TrackedObject } from '../lib/api'
import { iconFor, placeName } from '../lib/format'
import { pinColor } from '../lib/pins'
import { SnapshotPhoto } from './SnapshotPhoto'

/** The items beside the map, in the title panel: photo, name and where it is. Hovering one lights up its pin. */
export function ItemPanel({ objects, activeId, onHover, onOpen }: {
  objects: TrackedObject[]
  activeId: string | null
  onHover: (id: string | null) => void
  onOpen: (id: string) => void
}) {
  const sorted = [...objects.filter((o) => o.seen), ...objects.filter((o) => !o.seen)]
  return (
    <ul className="space-y-2">
      {sorted.map((o) => {
        const Icon = iconFor(o.icon)
        return (
          <li key={o.object_id} id={`item-${o.object_id}`}>
            <button
              onClick={() => onOpen(o.object_id)}
              onMouseEnter={() => onHover(o.object_id)}
              onMouseLeave={() => onHover(null)}
              className={`bubble press ${o.object_id === activeId ? 'active' : ''}`}
            >
              <span className="bubble-photo">
                {o.snapshot ? (
                  <SnapshotPhoto snapshot={o.snapshot} alt={`Last photo of your ${o.name.toLowerCase()}`} />
                ) : (
                  <Icon className="size-5 text-deep" strokeWidth={1.75} />
                )}
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate font-medium">{o.name}</span>
                <span className="flex items-center gap-1.5 truncate text-[13px] text-muted">
                  {o.seen && <span aria-hidden className="size-2 shrink-0 rounded-full" style={{ background: pinColor(o) }} />}
                  {o.seen ? placeName(o.region!) : 'Not yet seen'}
                </span>
              </span>
            </button>
          </li>
        )
      })}
    </ul>
  )
}
