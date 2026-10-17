import { useEffect, useRef, useState } from 'react'
import { LoaderCircle, Plus, Trash2 } from 'lucide-react'
import { api } from '../lib/api'
import type { Health, Region } from '../lib/api'
import { LiveFeed } from './CameraPanel'

type Area = { id: number; name: string; kind: string; x0: number; y0: number; x1: number; y1: number }

const HUES = [40, 150, 260, 320, 80, 200, 0, 110]
const color = (i: number) => `oklch(0.62 0.13 ${HUES[i % HUES.length]})`
const clamp01 = (v: number) => Math.min(1, Math.max(0, v))
let nextId = 1

/** Drag an area to move it, drag its corner to resize. Arrow keys nudge (Shift+arrows resize). */
function AreaEditor({ image, areas, onChange }: { image: string; areas: Area[]; onChange: (a: Area[]) => void }) {
  const box = useRef<HTMLDivElement>(null)
  const drag = useRef<{ id: number; mode: 'move' | 'resize'; px: number; py: number; start: Area } | null>(null)

  const update = (a: Area) => onChange(areas.map((o) => (o.id === a.id ? a : o)))
  const moved = (s: Area, dx: number, dy: number): Area => {
    const w = s.x1 - s.x0, h = s.y1 - s.y0
    const x0 = Math.min(1 - w, Math.max(0, s.x0 + dx)), y0 = Math.min(1 - h, Math.max(0, s.y0 + dy))
    return { ...s, x0, y0, x1: x0 + w, y1: y0 + h }
  }
  const resized = (s: Area, dx: number, dy: number): Area =>
    ({ ...s, x1: Math.max(s.x0 + 0.04, clamp01(s.x1 + dx)), y1: Math.max(s.y0 + 0.04, clamp01(s.y1 + dy)) })

  function onMove(e: React.PointerEvent) {
    const d = drag.current
    if (!d || !box.current) return
    const b = box.current.getBoundingClientRect()
    const dx = (e.clientX - d.px) / b.width, dy = (e.clientY - d.py) / b.height
    update(d.mode === 'move' ? moved(d.start, dx, dy) : resized(d.start, dx, dy))
  }

  function onKey(a: Area, e: React.KeyboardEvent) {
    const k = ({ ArrowLeft: [-0.01, 0], ArrowRight: [0.01, 0], ArrowUp: [0, -0.01], ArrowDown: [0, 0.01] } as Record<string, number[]>)[e.key]
    if (!k) return
    e.preventDefault()
    update(e.shiftKey ? resized(a, k[0], k[1]) : moved(a, k[0], k[1]))
  }

  return (
    <div
      ref={box}
      className="relative touch-none overflow-hidden rounded-xl bg-ink select-none"
      onPointerMove={onMove}
      onPointerUp={() => (drag.current = null)}
      onPointerCancel={() => (drag.current = null)}
    >
      <img src={image} alt="Still photo from the camera" className="block h-auto w-full" draggable={false} />
      <div aria-hidden className="pointer-events-none absolute inset-0 rounded-[inherit] outline-1 -outline-offset-1 outline-black/10" />
      {areas.map((a, i) => (
        <div
          key={a.id}
          role="group"
          tabIndex={0}
          aria-label={`${a.name || 'Unnamed'} area. Arrow keys move it; Shift and arrow keys resize it.`}
          onKeyDown={(e) => onKey(a, e)}
          onPointerDown={(e) => {
            box.current?.setPointerCapture(e.pointerId)
            drag.current = { id: a.id, mode: 'move', px: e.clientX, py: e.clientY, start: a }
          }}
          className="absolute cursor-move rounded-md border-2 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white"
          style={{
            left: `${a.x0 * 100}%`, top: `${a.y0 * 100}%`, width: `${(a.x1 - a.x0) * 100}%`, height: `${(a.y1 - a.y0) * 100}%`,
            borderColor: color(i), background: `color-mix(in oklch, ${color(i)} 14%, transparent)`,
          }}
        >
          <span className="absolute top-1 left-1 max-w-[calc(100%-8px)] truncate rounded px-1.5 py-0.5 text-[12px] font-semibold text-white" style={{ background: color(i) }}>
            {a.name || 'Unnamed'}
          </span>
          <span
            aria-hidden
            onPointerDown={(e) => {
              e.stopPropagation()
              box.current?.setPointerCapture(e.pointerId)
              drag.current = { id: a.id, mode: 'resize', px: e.clientX, py: e.clientY, start: a }
            }}
            className="absolute right-0.5 bottom-0.5 size-5 cursor-nwse-resize rounded-full border-2 border-white"
            style={{ background: color(i) }}
          />
        </div>
      ))}
    </div>
  )
}

export function ScanFlow({ health, regions, onSaved, onClose }: {
  health: Health
  regions: Region[]
  onSaved: (r: Region[]) => void
  onClose: () => void
}) {
  const dialog = useRef<HTMLDialogElement>(null)
  const [areas, setAreas] = useState<Area[] | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const { mode, reference_ready: ready, proposal } = health

  useEffect(() => {
    if (!dialog.current?.open) dialog.current?.showModal()
  }, [])

  useEffect(() => {
    if (mode === 'MONITORING') onClose()
  }, [mode, onClose])

  // Seed the editor once from what the scan found (or the previous areas if it found nothing).
  useEffect(() => {
    if (!ready || areas) return
    const seed = proposal.length
      ? proposal.map((p) => ({ name: p.name, kind: p.kind, x0: p.camera[0], y0: p.camera[1], x1: p.camera[2], y1: p.camera[3] }))
      : regions
    setAreas(seed.map((a) => ({ ...a, id: nextId++ })))
  }, [ready, proposal, regions, areas])

  async function step(fn: () => Promise<unknown>) {
    setBusy(true)
    setError(null)
    try {
      await fn()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Something went wrong')
    } finally {
      setBusy(false)
    }
  }

  const save = () =>
    step(async () => {
      const saved = await api.saveRegions(areas!.map((a) => ({ name: a.name.trim(), kind: a.kind, camera: [a.x0, a.y0, a.x1, a.y1] })))
      onSaved(saved)
      await api.reposition('resume')
    })

  const addArea = () =>
    setAreas((cur) => [...(cur ?? []), { id: nextId++, name: `Area ${(cur?.length ?? 0) + 1}`, kind: 'custom', x0: 0.35, y0: 0.35, x1: 0.65, y1: 0.65 }])

  const primary = 'press flex h-11 items-center justify-center gap-2 rounded-xl bg-ink px-5 font-medium text-white hover:bg-ink/85 disabled:opacity-50'
  const secondary = 'press flex h-11 items-center justify-center rounded-xl px-4 font-medium text-ink hover:bg-sunken disabled:opacity-50'
  const found = proposal.map((p) => p.name)
  const cancelButton = (
    <button disabled={busy} onClick={() => step(() => api.reposition('cancel'))} className={secondary}>
      Cancel
    </button>
  )

  return (
    <dialog
      ref={dialog}
      onCancel={(e) => e.preventDefault()} // closing mid-scan would leave monitoring paused
      aria-labelledby="scan-title"
      className="enter m-auto max-h-[94dvh] w-[min(820px,calc(100vw-24px))] overflow-y-auto overscroll-contain rounded-[20px] border border-transparent bg-surface p-0 text-ink shadow-overlay backdrop:bg-black/30"
    >
      <div className="space-y-4 p-6">
        <p className="text-[13px] font-medium text-caution">Monitoring paused while you scan</p>

        {mode === 'REPOSITIONING' && (
          <>
            <div>
              <h2 id="scan-title" className="text-lg font-semibold">Scan room</h2>
              <p className="mt-1 text-muted">
                Point the camera at the room. Moving it now won’t count as items moving. When it’s still, press Scan and
                Keepsake will look for the furniture in view.
              </p>
            </div>
            <LiveFeed health={health} className="aspect-video rounded-xl" />
            <div className="flex flex-wrap gap-2">
              <button disabled={busy} onClick={() => step(() => api.reposition('finish'))} className={primary}>Scan</button>
              {cancelButton}
            </div>
          </>
        )}

        {mode === 'CALIBRATING' && !ready && (
          <>
            <h2 id="scan-title" className="text-lg font-semibold">Scanning…</h2>
            <p className="flex items-center gap-2 text-muted">
              <LoaderCircle className="size-4 animate-spin motion-reduce:animate-none" strokeWidth={1.75} />
              Hold the camera still for a moment.
            </p>
            <LiveFeed health={health} className="aspect-video rounded-xl" />
            <div className="flex flex-wrap gap-2">{cancelButton}</div>
          </>
        )}

        {(mode === 'CALIBRATING' || mode === 'READY_TO_RESUME') && ready && areas && (
          <>
            <div>
              <h2 id="scan-title" className="text-lg font-semibold">Review areas</h2>
              <p className="mt-1 text-muted">
                {found.length
                  ? `Found ${found.join(', ')}. Rename them (a table might be your desk), adjust the boxes, or add areas it missed, like a dresser or shelf.`
                  : 'No furniture was recognized. Add areas by hand, or save with none and Keepsake will describe places by side of the room.'}
              </p>
            </div>
            <AreaEditor image={`${api.referenceUrl}?t=${health.view_id}-${found.length}`} areas={areas} onChange={setAreas} />
            <ul className="divide-y divide-hairline rounded-xl border border-hairline">
              {areas.map((a, i) => (
                <li key={a.id} className="flex items-center gap-3 px-3 py-2">
                  <span aria-hidden className="size-3 shrink-0 rounded-sm" style={{ background: color(i) }} />
                  <label className="sr-only" htmlFor={`area-${a.id}`}>Area name</label>
                  <input
                    id={`area-${a.id}`}
                    value={a.name}
                    maxLength={32}
                    onChange={(e) => setAreas(areas.map((o) => (o.id === a.id ? { ...o, name: e.target.value } : o)))}
                    className="h-9 min-w-0 flex-1 rounded-lg border border-transparent bg-transparent px-2 outline-none hover:border-hairline focus:border-ink/40"
                  />
                  {a.kind !== 'custom' && <span className="hidden text-[13px] text-faint sm:inline">detected</span>}
                  <button
                    onClick={() => setAreas(areas.filter((o) => o.id !== a.id))}
                    aria-label={`Remove ${a.name || 'area'}`}
                    className="press flex size-9 items-center justify-center rounded-lg text-muted hover:bg-sunken hover:text-danger"
                  >
                    <Trash2 className="size-4" strokeWidth={1.75} />
                  </button>
                </li>
              ))}
              <li>
                <button onClick={addArea} className="press flex h-11 w-full items-center gap-2 px-3 text-left font-medium text-muted hover:text-ink">
                  <Plus className="size-4" strokeWidth={1.75} /> Add area
                </button>
              </li>
            </ul>
            <div className="flex flex-wrap gap-2">
              <button disabled={busy} onClick={save} className={primary}>Save and resume</button>
              {cancelButton}
            </div>
            <p className="text-[13px] text-muted">Cancel keeps your previous areas and resumes watching.</p>
          </>
        )}

        {error && <p className="text-caution">{error}</p>}
      </div>
    </dialog>
  )
}
