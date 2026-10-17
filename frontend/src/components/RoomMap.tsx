import type { Region, TrackedObject } from '../lib/api'
import { iconFor } from '../lib/format'

interface Props {
  regions: Region[]
  objects: TrackedObject[]
  highlightId: string | null
  onOpen: (id: string) => void
  onScan: () => void
  /** Reference photo from the last scan, if the backend still has it. */
  referenceUrl: string | null
}

/** Nudge markers sideways so items remembered at nearly the same spot don't hide each other. */
function spread<T extends { left: number; top: number }>(items: T[]): T[] {
  const taken: { left: number; top: number }[] = []
  return items.map((it) => {
    const pos = { ...it }
    for (let i = 0; i < 8 && taken.some((p) => Math.abs(p.left - pos.left) < 6 && Math.abs(p.top - pos.top) < 9); i++) {
      pos.left += pos.left > 85 ? -6 : 6
    }
    taken.push(pos)
    return pos
  })
}

/**
 * The room as the camera sees it: scanned areas as outlines, items at their last-seen spot.
 * A recent memory photo sits faintly underneath so the layout is recognizable.
 */
export function RoomMap({ regions, objects, highlightId, onOpen, onScan, referenceUrl }: Props) {
  const placed = spread(
    objects.filter((o) => o.seen && o.x != null && o.y != null).map((o) => ({ o, left: o.x! * 100, top: o.y! * 100 })),
  )
  const backdrop = objects
    .filter((o) => o.snapshot && !o.awaiting_reconfirmation)
    .map((o) => o.snapshot!)
    .sort((a, b) => b.timestamp.localeCompare(a.timestamp))[0]
  const unseen = objects.filter((o) => !o.seen)

  return (
    <div className="space-y-3">
      <div className="card relative aspect-video w-full overflow-hidden bg-sunken">
        {(referenceUrl || backdrop) && (
          <img src={referenceUrl ?? backdrop!.image_url} alt="" aria-hidden className="absolute inset-0 size-full object-cover opacity-30 grayscale" />
        )}
        {regions.map((r) => (
          <div
            key={r.name}
            className="absolute rounded-lg border border-ink/25 bg-surface/55"
            style={{ left: `${r.x0 * 100}%`, top: `${r.y0 * 100}%`, width: `${(r.x1 - r.x0) * 100}%`, height: `${(r.y1 - r.y0) * 100}%` }}
          >
            <span className="absolute top-1.5 left-2 text-[12px] font-medium text-ink/70">{r.name}</span>
          </div>
        ))}

        {placed.map(({ o, left, top }) => {
          const Icon = iconFor(o.icon)
          const highlighted = o.object_id === highlightId
          const tone = o.awaiting_reconfirmation
            ? 'border-dashed border-caution/60 bg-caution-soft text-caution'
            : o.visible ? 'border-transparent bg-ink text-white' : 'border-dashed border-ink/40 bg-surface text-ink'
          return (
            <button
              key={o.object_id}
              onClick={() => onOpen(o.object_id)}
              style={{ left: `${left}%`, top: `${top}%` }}
              className="absolute z-10 flex -translate-x-1/2 -translate-y-1/2 flex-col items-center transition-[left,top] duration-500 ease-out motion-reduce:transition-none"
              aria-label={`${o.name}${o.visible ? ', in view now' : ', last seen here'}`}
            >
              <span className={`press flex size-9 items-center justify-center rounded-full border-2 shadow-raised sm:size-10 ${tone} ${highlighted ? 'outline-2 outline-offset-2 outline-ink' : ''}`}>
                <Icon className="size-4 sm:size-[18px]" strokeWidth={1.75} />
              </span>
              <span className={`mt-1 rounded-md bg-surface px-1.5 py-0.5 text-[12px] font-medium whitespace-nowrap shadow-ring ${highlighted ? '' : 'hidden sm:block'}`}>
                {o.name}
              </span>
            </button>
          )
        })}

        {regions.length === 0 && (
          <div className="absolute inset-x-0 bottom-0 flex flex-wrap items-center justify-between gap-2 bg-surface/90 px-4 py-3 backdrop-blur">
            <p className="text-muted">No areas yet. Scan the room so Keepsake can name its furniture.</p>
            <button onClick={onScan} className="press min-h-9 rounded-lg bg-ink px-3 text-[13px] font-medium text-white hover:bg-ink/85">
              Scan room
            </button>
          </div>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-[13px] text-muted">
        <span className="flex items-center gap-1.5"><span className="size-2.5 rounded-full bg-ink" /> In view</span>
        <span className="flex items-center gap-1.5"><span className="size-2.5 rounded-full border border-dashed border-ink/50" /> Last seen</span>
        <span className="flex items-center gap-1.5"><span className="size-2.5 rounded-full border border-dashed border-caution bg-caution-soft" /> Before last scan</span>
        <span>Shown as the camera sees the room.</span>
      </div>

      {unseen.length > 0 && <p className="text-[13px] text-muted">Not yet seen: {unseen.map((o) => o.name).join(', ')}</p>}
    </div>
  )
}
