import type { TrackedObject } from '../lib/api'
import { iconFor, placeName, statusLabel, timeAgo } from '../lib/format'
import { SnapshotPhoto } from './SnapshotPhoto'

const DOT = { live: 'bg-live', past: 'bg-faint', warn: 'bg-caution', none: 'bg-hairline' }
const TEXT = { live: 'text-live', past: 'text-muted', warn: 'text-caution', none: 'text-faint' }

export function Status({ o }: { o: TrackedObject }) {
  const { label, tone } = statusLabel(o)
  return (
    <span className={`inline-flex items-center gap-1.5 text-[13px] font-medium ${TEXT[tone]}`}>
      <span aria-hidden className={`size-1.5 rounded-full ${DOT[tone]}`} />
      {label}
    </span>
  )
}

function ObjectCard({ o, now, highlighted, onOpen }: {
  o: TrackedObject
  now: number
  highlighted: boolean
  onOpen: () => void
}) {
  const Icon = iconFor(o.icon)
  return (
    <button
      onClick={onOpen}
      className={`card press group flex w-full flex-col overflow-hidden text-left hover:border-deep/40 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-deep ${highlighted ? 'outline-2 outline-offset-2 outline-deep' : ''}`}
    >
      <div className="photo-well aspect-[4/3] w-full">
        {o.snapshot ? (
          <SnapshotPhoto snapshot={o.snapshot} alt={`Last photo of your ${o.name.toLowerCase()}`} />
        ) : (
          <div className="flex size-full items-center justify-center text-deep/60">
            <Icon className="size-8" strokeWidth={1.5} />
          </div>
        )}
      </div>
      <div className="flex flex-col gap-1 px-4 pt-3 pb-4">
        <div className="flex items-center gap-2">
          <Icon className="size-4 shrink-0 text-muted" strokeWidth={1.75} />
          <h3 className="font-semibold">{o.name}</h3>
        </div>
        <p className="text-muted">
          {o.seen ? (
            <>
              <span className="text-ink">{placeName(o.region!)}</span>
              <span aria-hidden> · </span>
              <span className="tabular-nums">{timeAgo(o.last_seen!, now)}</span>
            </>
          ) : 'Not yet seen'}
        </p>
        {o.seen && <Status o={o} />}
      </div>
    </button>
  )
}

export function ObjectList({ objects, now, highlightId, onOpen }: {
  objects: TrackedObject[]
  now: number
  highlightId: string | null
  onOpen: (id: string) => void
}) {
  const seen = objects.filter((o) => o.seen)
  const unseen = objects.filter((o) => !o.seen)
  return (
    <div className="space-y-6">
      {seen.length === 0 && (
        <div className="card px-5 py-4">
          <p className="font-semibold">Nothing remembered yet</p>
          <p className="mt-0.5 text-muted">
            Put one of these items where the camera can see it and leave it for a moment. Keepsake saves a photo once it
            settles.
          </p>
        </div>
      )}
      <ul className="grid grid-cols-2 gap-3 sm:gap-4 xl:grid-cols-3">
        {[...seen, ...unseen].map((o) => (
          <li key={o.object_id} className="flex">
            <ObjectCard o={o} now={now} highlighted={o.object_id === highlightId} onOpen={() => onOpen(o.object_id)} />
          </li>
        ))}
      </ul>
    </div>
  )
}
