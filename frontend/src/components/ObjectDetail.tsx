import { useEffect, useRef, useState } from 'react'
import { X } from 'lucide-react'
import { api } from '../lib/api'
import type { Snapshot, TrackedObject } from '../lib/api'
import { EVENT_LABEL, fullTime, iconFor, timeAgo } from '../lib/format'
import { SnapshotPhoto } from './SnapshotPhoto'
import { Status } from './ObjectList'

export function ObjectDetail({ o, now, onClose }: { o: TrackedObject; now: number; onClose: () => void }) {
  const [history, setHistory] = useState<Snapshot[]>([])
  const [pickedId, setPickedId] = useState<number | null>(null)
  const dialog = useRef<HTMLDialogElement>(null)
  const Icon = iconFor(o.icon)
  const latestId = o.snapshot?.id

  useEffect(() => {
    dialog.current?.showModal()
  }, [])

  useEffect(() => {
    if (!o.seen) return
    api.snapshots(o.object_id).then(setHistory).catch(() => setHistory([]))
  }, [o.object_id, o.seen, latestId])

  const shown = history.find((s) => s.id === pickedId) ?? o.snapshot
  const isLatest = !shown || shown.id === latestId
  const when = isLatest ? o.last_seen : shown?.timestamp

  return (
    <dialog
      ref={dialog}
      onClose={onClose}
      onClick={(e) => e.target === dialog.current && dialog.current?.close()}
      aria-labelledby="detail-title"
      className="enter m-auto max-h-[92dvh] w-[min(720px,calc(100vw-24px))] overflow-y-auto overscroll-contain rounded-[20px] border border-transparent bg-surface p-0 text-ink shadow-overlay backdrop:bg-black/30"
    >
      <div className="flex items-center justify-between gap-4 px-6 pt-5 pb-4">
        <div className="flex items-center gap-3">
          <Icon className="size-5 text-muted" strokeWidth={1.75} />
          <div>
            <h2 id="detail-title" className="text-lg font-semibold">{o.name}</h2>
            {o.seen && <Status o={o} />}
          </div>
        </div>
        <button
          onClick={() => dialog.current?.close()}
          className="press -mr-2 flex size-10 items-center justify-center rounded-lg text-muted hover:bg-sunken hover:text-ink"
          aria-label="Close"
        >
          <X className="size-5" strokeWidth={1.75} />
        </button>
      </div>

      <div className="px-6 pb-6">
        {!o.seen ? (
          <div className="rounded-xl bg-sunken px-6 py-10 text-center">
            <Icon className="mx-auto size-8 text-faint" strokeWidth={1.5} />
            <p className="mt-3 font-semibold">Not yet seen</p>
            <p className="mx-auto mt-1 max-w-sm text-muted">
              Place your {o.name.toLowerCase()} where the camera can see it. Keepsake will remember it with a photo.
            </p>
          </div>
        ) : (
          <>
            {shown ? (
              <SnapshotPhoto snapshot={shown} full alt={`Photo of your ${o.name.toLowerCase()}`} className="rounded-xl" />
            ) : (
              <div className="flex aspect-video items-center justify-center rounded-xl bg-sunken p-6 text-center text-muted">
                No photo was saved for this sighting. Photo saving may have been paused.
              </div>
            )}

            <dl className="mt-5">
              <dt className="text-[13px] text-muted">{isLatest ? 'Last seen' : 'Photo taken'}</dt>
              <dd className="text-lg font-semibold tabular-nums">{when && fullTime(when)}</dd>
              <dd className="text-[13px] text-muted">{when && timeAgo(when, now)}</dd>
            </dl>

            {isLatest && <Note o={o} />}

            {history.length > 1 && (
              <section className="mt-6 border-t border-hairline pt-4">
                <h3 className="mb-3 text-[13px] font-medium text-muted">Earlier photos</h3>
                <ul className="-mx-1 flex gap-3 overflow-x-auto overscroll-x-contain px-1 pb-1">
                  {history.map((s) => (
                    <li key={s.id} className="w-32 shrink-0">
                      <button
                        onClick={() => setPickedId(s.id)}
                        aria-pressed={shown?.id === s.id}
                        className="press block w-full text-left"
                      >
                        <div className={`aspect-[4/3] overflow-hidden rounded-lg ${shown?.id === s.id ? 'outline-2 outline-offset-2 outline-ink' : ''}`}>
                          <SnapshotPhoto snapshot={s} alt={`${o.name}, ${fullTime(s.timestamp)}`} />
                        </div>
                        <div className="mt-1.5 text-[13px] leading-tight">
                          <div className="truncate font-medium">{EVENT_LABEL[s.event_type] ?? 'Seen'}</div>
                          <div className="text-muted">{timeAgo(s.timestamp, now)}</div>
                        </div>
                      </button>
                    </li>
                  ))}
                </ul>
              </section>
            )}
          </>
        )}
      </div>
    </dialog>
  )
}

function Note({ o }: { o: TrackedObject }) {
  const text = o.visible ? null : "It's out of view right now, so it may have moved since this photo."
  return text ? <p className="mt-4 rounded-xl bg-caution-soft px-4 py-3 text-caution">{text}</p> : null
}
