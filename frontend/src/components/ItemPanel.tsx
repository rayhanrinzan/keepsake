import type { TrackedObject } from '../lib/api'
import { iconFor, placeName } from '../lib/format'
import { pinColor } from '../lib/pins'
import { useState } from 'react'

/**
 * The item's picture: its latest camera photo, zoomed in on the item; otherwise a PNG from
 * /public/items/<icon>.png if one has been added; otherwise its icon.
 */
function Thumb({ o }: { o: TrackedObject }) {
  const [noPng, setNoPng] = useState(false)
  const Icon = iconFor(o.icon)
  if (o.snapshot) {
    const [x0, y0, x1, y1] = o.snapshot.bbox
    const zoom = Math.min(6, 0.8 / Math.max(x1 - x0, y1 - y0, 0.01))
    return (
      <img
        src={o.snapshot.image_url}
        alt=""
        loading="lazy"
        className="size-full object-cover"
        style={{ transformOrigin: `${((x0 + x1) / 2) * 100}% ${((y0 + y1) / 2) * 100}%`, transform: `scale(${zoom})` }}
      />
    )
  }
  if (!noPng) return <img src={`/items/${o.icon}.png`} alt="" className="size-full object-contain p-1" onError={() => setNoPng(true)} />
  return <Icon className="size-5" strokeWidth={1.75} />
}

/** The items beside the map, in the title panel: picture, name and where it is. Hovering one lights up its pin; clicking shows its photo on the map. */
export function ItemPanel({ objects, activeId, onHover, onPick }: {
  objects: TrackedObject[]
  activeId: string | null
  onHover: (id: string | null) => void
  onPick: (id: string) => void
}) {
  const sorted = [...objects.filter((o) => o.seen), ...objects.filter((o) => !o.seen)]
  return (
    <ul className="space-y-2">
      {sorted.map((o) => {
        return (
          <li key={o.object_id} id={`item-${o.object_id}`}>
            <button
              onClick={() => onPick(o.object_id)}
              onMouseEnter={() => onHover(o.object_id)}
              onMouseLeave={() => onHover(null)}
              className={`bubble press ${o.object_id === activeId ? 'active' : ''}`}
            >
              <span className="bubble-photo"><Thumb o={o} /></span>
              <span className="min-w-0 flex-1">
                <span className="block truncate font-medium">{o.name}</span>
                <span className="flex items-center gap-1.5 truncate text-[13px] text-muted">
                  {o.seen && <span aria-hidden className="size-2 shrink-0 rounded-full ring-1 ring-black/15" style={{ background: pinColor(o) }} />}
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
