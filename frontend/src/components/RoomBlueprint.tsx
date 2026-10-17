import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { PointerEvent as ReactPointerEvent, WheelEvent } from 'react'
import { Box, Minus, Plus, RotateCcw, RotateCw, Square } from 'lucide-react'
import type { Region, TrackedObject } from '../lib/api'
import { PIN, pinColor } from '../lib/pins'

/*
 * The room as a 3D blueprint: floor, the two back walls, scanned furniture as
 * see-through boxes and a pin per item. It is drawn from the camera's view
 * (image left/right = room width, image top = back wall), so it shows the same
 * spots the camera saw, just from a more readable angle. Nothing is guessed:
 * only items with a remembered position get a pin.
 * Scroll or use the buttons to zoom, drag to pan, rotate to look from another corner.
 */

const ROOM_W = 100
const ROOM_D = 70
const WALL = 24
const C = Math.cos(Math.PI / 6)
const S = 0.5
const MIN_ZOOM = 0.5
const MAX_ZOOM = 8
const STRETCH = 1.25 // how far past a limit a zoom can stretch before it springs back

type View = { s: number; tx: number; ty: number }
const HOME: View = { s: 1, tx: 0, ty: 0 }

/** Rough furniture heights in room units, for the 3D boxes. */
const HEIGHT: Record<string, number> = {
  bed: 10, couch: 12, chair: 14, 'dining table': 15, bench: 9, tv: 18,
  refrigerator: 30, oven: 18, microwave: 8, sink: 16, toilet: 8,
}

type Mode = '3d' | 'top'
type Pt = [number, number]
type Rect = { x0: number; y0: number; x1: number; y1: number }

const LINE = 'rgba(47,111,224,0.75)'
const GRID = 'rgba(47,111,224,0.08)'

/** Camera-space rectangle (0..1) to room units. */
const toRoom = (r: Rect): Rect => ({ x0: r.x0 * ROOM_W, y0: r.y0 * ROOM_D, x1: r.x1 * ROOM_W, y1: r.y1 * ROOM_D })

/** Rotates room coordinates in quarter turns so the room can be seen from any corner. */
function frame(turns: number) {
  const k = ((turns % 4) + 4) % 4
  const w = k % 2 ? ROOM_D : ROOM_W
  const h = k % 2 ? ROOM_W : ROOM_D
  const pt = (x: number, y: number): Pt =>
    k === 0 ? [x, y] : k === 1 ? [ROOM_D - y, x] : k === 2 ? [ROOM_W - x, ROOM_D - y] : [y, ROOM_W - x]
  const rect = (r: Rect): Rect => {
    const a = pt(r.x0, r.y0)
    const b = pt(r.x1, r.y1)
    return { x0: Math.min(a[0], b[0]), y0: Math.min(a[1], b[1]), x1: Math.max(a[0], b[0]), y1: Math.max(a[1], b[1]) }
  }
  return { w, h, pt, rect }
}

const projector = (mode: Mode) => (x: number, y: number, z = 0): Pt =>
  mode === 'top' ? [x, y] : [(x - y) * C, (x + y) * S - z]

const poly = (pts: Pt[]) => pts.map((p) => p.join(',')).join(' ')

/** The smallest scanned area an item sits in, so its pin rests on that furniture. */
function areaOf(o: TrackedObject, regions: Region[]) {
  const inside = regions.filter((r) => o.x! >= r.x0 && o.x! <= r.x1 && o.y! >= r.y0 && o.y! <= r.y1)
  return inside.sort((a, b) => (a.x1 - a.x0) * (a.y1 - a.y0) - (b.x1 - b.x0) * (b.y1 - b.y0))[0]
}

interface Props {
  regions: Region[]
  objects: TrackedObject[]
  highlightId: string | null
  onSelect: (id: string) => void
}

export function RoomBlueprint({ regions, objects, highlightId, onSelect }: Props) {
  const [mode, setModeState] = useState<Mode>('3d')
  const [turns, setTurns] = useState(0)
  // `view` is what's drawn; `target` is where it's heading. A spring eases one
  // toward the other, and zooming past the limits stretches then bounces back, like Figma.
  const [view, setView] = useState<View>(HOME)
  const target = useRef<View>(HOME)
  const shown = useRef<View>(HOME)
  const frameId = useRef(0)
  const settle = useRef(0)
  const animate = useCallback(() => {
    if (frameId.current) return
    const step = () => {
      const v = shown.current
      const t = target.current
      const next = { s: v.s + (t.s - v.s) * 0.28, tx: v.tx + (t.tx - v.tx) * 0.28, ty: v.ty + (t.ty - v.ty) * 0.28 }
      const done = Math.abs(t.s - next.s) < 0.0005 && Math.abs(t.tx - next.tx) < 0.01 && Math.abs(t.ty - next.ty) < 0.01
      shown.current = done ? t : next
      setView(shown.current)
      frameId.current = done ? 0 : requestAnimationFrame(step)
    }
    frameId.current = requestAnimationFrame(step)
  }, [])
  useEffect(() => () => { cancelAnimationFrame(frameId.current); clearTimeout(settle.current) }, [])
  const reset = () => { target.current = HOME; animate() }
  // A new perspective starts from the whole room.
  const snapHome = () => { cancelAnimationFrame(frameId.current); frameId.current = 0; target.current = shown.current = HOME; setView(HOME) }
  const setMode = (m: Mode) => { setModeState(m); snapHome() }
  const turn = (d: number) => { setTurns((t) => t + d); snapHome() }
  const svgRef = useRef<SVGSVGElement>(null)
  const drag = useRef<{ x: number; y: number; moved: boolean } | null>(null)
  const suppressClick = useRef(false)

  const f = useMemo(() => frame(turns), [turns])
  const p = useMemo(() => projector(mode), [mode])
  const is3d = mode === '3d'

  const viewBox = useMemo(() => {
    // The items panel floats over the left of the map, so the room sits a little right of center.
    if (mode === 'top') return [-6 - f.w * 0.45, -10, f.w * 1.45 + 12, f.h + 18]
    const pts = [p(0, 0, WALL), p(f.w, 0, WALL), p(0, f.h, WALL), p(f.w, f.h, 0), p(0, f.h, 0), p(f.w, 0, 0)]
    const xs = pts.map((q) => q[0])
    const ys = pts.map((q) => q[1])
    const pad = 8
    const w = Math.max(...xs) - Math.min(...xs)
    const left = w * 0.4
    return [Math.min(...xs) - pad - left, Math.min(...ys) - pad, w + pad * 2 + left, Math.max(...ys) - Math.min(...ys) + pad * 2]
  }, [mode, f.w, f.h, p])

  // Coordinates of a screen point inside the viewBox.
  const toSvg = useCallback((clientX: number, clientY: number) => {
    const m = svgRef.current?.getScreenCTM()
    if (!m) return { x: 0, y: 0 }
    const q = new DOMPoint(clientX, clientY).matrixTransform(m.inverse())
    return { x: q.x, y: q.y }
  }, [])

  const scaleAround = (v: View, s: number, c: { x: number; y: number }): View => {
    const k = s / v.s
    return { s, tx: c.x - (c.x - v.tx) * k, ty: c.y - (c.y - v.ty) * k }
  }

  const zoomAt = useCallback((factor: number, at?: { x: number; y: number }) => {
    const c = at ?? { x: viewBox[0] + viewBox[2] / 2, y: viewBox[1] + viewBox[3] / 2 }
    const v = target.current
    let s = v.s * factor
    // Past a limit the zoom gets heavy (rubber band), then springs back once you stop.
    if (s > MAX_ZOOM) s = Math.min(MAX_ZOOM * STRETCH, MAX_ZOOM * (s / MAX_ZOOM) ** 0.3)
    if (s < MIN_ZOOM) s = Math.max(MIN_ZOOM / STRETCH, MIN_ZOOM * (s / MIN_ZOOM) ** 0.3)
    target.current = scaleAround(v, s, c)
    animate()
    clearTimeout(settle.current)
    settle.current = setTimeout(() => {
      const t = target.current
      const limit = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, t.s))
      if (limit !== t.s) { target.current = scaleAround(t, limit, c); animate() }
    }, 160)
  }, [viewBox, animate])

  // Zoom follows the wheel or pinch directly, in proportion to how far it moved.
  // A trackpad pinch arrives as a wheel event with ctrlKey and small deltas.
  const onWheel = (e: WheelEvent<SVGSVGElement>) => {
    const dy = e.deltaMode === 1 ? e.deltaY * 16 : e.deltaY
    const speed = e.ctrlKey ? 0.012 : 0.004
    zoomAt(Math.min(2, Math.max(0.5, Math.exp(-dy * speed))), toSvg(e.clientX, e.clientY))
  }

  // Keep the page from scrolling while the wheel zooms the map.
  useEffect(() => {
    const svg = svgRef.current
    if (!svg) return
    const block = (e: globalThis.WheelEvent) => e.preventDefault()
    svg.addEventListener('wheel', block, { passive: false })
    return () => svg.removeEventListener('wheel', block)
  }, [])

  const onPointerDown = (e: ReactPointerEvent<SVGSVGElement>) => {
    if (e.button !== 0) return
    drag.current = { x: e.clientX, y: e.clientY, moved: false }
    const move = (ev: PointerEvent) => {
      const d = drag.current
      if (!d) return
      const a = toSvg(d.x, d.y)
      const b = toSvg(ev.clientX, ev.clientY)
      if (Math.hypot(ev.clientX - d.x, ev.clientY - d.y) > 3) d.moved = true
      d.x = ev.clientX
      d.y = ev.clientY
      // Panning tracks the pointer exactly, no easing.
      const t = target.current
      target.current = { ...t, tx: t.tx + (b.x - a.x), ty: t.ty + (b.y - a.y) }
      shown.current = { ...shown.current, tx: shown.current.tx + (b.x - a.x), ty: shown.current.ty + (b.y - a.y) }
      setView(shown.current)
    }
    const up = () => {
      suppressClick.current = !!drag.current?.moved
      drag.current = null
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
  }

  // Furniture, far to near, so nearer pieces draw on top.
  const furniture = regions
    .map((reg) => ({ reg, r: f.rect(toRoom(reg)), h: HEIGHT[reg.kind] ?? 8 }))
    .sort((a, b) => a.r.x0 + a.r.y0 + a.r.x1 + a.r.y1 - (b.r.x0 + b.r.y0 + b.r.x1 + b.r.y1))

  const pins = objects
    .filter((o) => o.seen && o.x != null && o.y != null)
    .map((o) => {
      const area = areaOf(o, regions)
      const [x, y] = f.pt(o.x! * ROOM_W, o.y! * ROOM_D)
      return { o, x, y, z: area ? HEIGHT[area.kind] ?? 8 : 0 }
    })
    .sort((a, b) => a.x + a.y - (b.x + b.y))

  const ns = { vectorEffect: 'non-scaling-stroke' as const }

  return (
    <div className="relative size-full">
      <svg
        ref={svgRef}
        className="blueprint size-full cursor-grab touch-none select-none active:cursor-grabbing"
        viewBox={viewBox.join(' ')}
        preserveAspectRatio="xMidYMid meet"
        onWheel={onWheel}
        onPointerDown={onPointerDown}
        role="img"
        aria-label="Blueprint of the room with a pin for each remembered item"
      >
        <g transform={`translate(${view.tx} ${view.ty}) scale(${view.s})`}>
          {/* Floor and its grid */}
          <polygon points={poly([p(0, 0), p(f.w, 0), p(f.w, f.h), p(0, f.h)])} fill="rgba(88,168,248,0.05)" />
          {Array.from({ length: Math.floor(f.w / 5) + 1 }, (_, i) => (
            <line key={`gx${i}`} {...ns} x1={p(i * 5, 0)[0]} y1={p(i * 5, 0)[1]} x2={p(i * 5, f.h)[0]} y2={p(i * 5, f.h)[1]} stroke={GRID} />
          ))}
          {Array.from({ length: Math.floor(f.h / 5) + 1 }, (_, i) => (
            <line key={`gy${i}`} {...ns} x1={p(0, i * 5)[0]} y1={p(0, i * 5)[1]} x2={p(f.w, i * 5)[0]} y2={p(f.w, i * 5)[1]} stroke={GRID} />
          ))}

          {/* Back walls (3D only); the front two are cut away so you can see in */}
          {is3d && (
            <>
              <polygon {...ns} points={poly([p(0, 0), p(0, f.h), p(0, f.h, WALL), p(0, 0, WALL)])} fill="rgba(88,168,248,0.06)" stroke={LINE} strokeWidth={1.4} />
              <polygon {...ns} points={poly([p(0, 0), p(f.w, 0), p(f.w, 0, WALL), p(0, 0, WALL)])} fill="rgba(88,168,248,0.10)" stroke={LINE} strokeWidth={1.4} />
            </>
          )}
          <polygon {...ns} points={poly([p(0, 0), p(f.w, 0), p(f.w, f.h), p(0, f.h)])} fill="none" stroke={LINE} strokeWidth={is3d ? 1.2 : 2} />

          {/* Scanned furniture as see-through boxes */}
          {furniture.map(({ reg, r, h }) => {
            const H = is3d ? h : 0
            const top = [p(r.x0, r.y0, H), p(r.x1, r.y0, H), p(r.x1, r.y1, H), p(r.x0, r.y1, H)]
            const left = [p(r.x0, r.y1), p(r.x1, r.y1), p(r.x1, r.y1, H), p(r.x0, r.y1, H)]
            const right = [p(r.x1, r.y0), p(r.x1, r.y1), p(r.x1, r.y1, H), p(r.x1, r.y0, H)]
            const front = p(r.x1, r.y1, 0)
            return (
              <g key={reg.name}>
                {is3d && <polygon {...ns} points={poly(left)} fill="rgba(47,111,224,0.20)" stroke={LINE} />}
                {is3d && <polygon {...ns} points={poly(right)} fill="rgba(47,111,224,0.11)" stroke={LINE} />}
                <polygon {...ns} points={poly(top)} fill="rgba(124,194,254,0.22)" stroke={LINE} />
                <text
                  x={is3d ? front[0] : r.x0 + 0.8}
                  y={is3d ? front[1] + 4 : r.y0 + 3}
                  className="blueprint-label"
                  textAnchor={is3d ? 'middle' : 'start'}
                >
                  {reg.name.toUpperCase()}
                </text>
              </g>
            )
          })}

          {/* Item pins: a dot floating over where it was last seen, with a drop line */}
          {pins.map(({ o, x, y, z }) => {
            const color = pinColor(o)
            const lift = is3d ? 4 : 0
            const base = p(x, y, is3d ? z : 0)
            const [px, py] = p(x, y, (is3d ? z : 0) + lift)
            const highlighted = o.object_id === highlightId
            const dashed = !o.visible
            return (
              <g
                key={o.object_id}
                className="blueprint-pin cursor-pointer"
                onClick={() => !suppressClick.current && onSelect(o.object_id)}
              >
                {is3d && <ellipse cx={base[0]} cy={base[1]} rx={2.6} ry={1.3} fill={color} opacity={0.25} />}
                {is3d && <line {...ns} x1={base[0]} y1={base[1]} x2={px} y2={py} stroke={color} strokeDasharray="2 2" />}
                {highlighted && <circle className="blueprint-ring" cx={px} cy={py} r={6.5} fill="none" stroke={color} strokeWidth={0.8} />}
                <circle cx={px} cy={py} r={4.2} fill={color} opacity={0.22} />
                <circle cx={px} cy={py} r={2.3} fill={dashed ? '#fff' : color} stroke={color} strokeWidth={0.7} strokeDasharray={dashed ? '1 0.7' : undefined} />
                <text x={px} y={py - 5} className="blueprint-name" textAnchor="middle">{o.name}</text>
              </g>
            )
          })}
        </g>
      </svg>

      <div className="absolute right-4 bottom-24 flex flex-wrap justify-end gap-2 sm:right-6 md:bottom-6">
        <div className="seg">
          <button className={is3d ? 'on' : ''} onClick={() => setMode('3d')} aria-label="3D view"><Box className="size-4" /> 3D</button>
          <button className={is3d ? '' : 'on'} onClick={() => setMode('top')} aria-label="Top-down view"><Square className="size-4" /> Top</button>
        </div>
        <div className="seg">
          <button onClick={() => turn(-1)} aria-label="Rotate left"><RotateCcw className="size-4" /></button>
          <button onClick={() => turn(1)} aria-label="Rotate right"><RotateCw className="size-4" /></button>
        </div>
        <div className="seg">
          <button onClick={() => zoomAt(1 / 1.6)} aria-label="Zoom out"><Minus className="size-4" /></button>
          <button className="w-14 justify-center tabular-nums" onClick={reset} aria-label="Reset zoom">
            {Math.round(view.s * 100)}%
          </button>
          <button onClick={() => zoomAt(1.6)} aria-label="Zoom in"><Plus className="size-4" /></button>
        </div>
      </div>
    </div>
  )
}

/** Color key for the pins. */
export function PinLegend() {
  const rows = [
    { color: PIN.live, label: 'In view now', dashed: false },
    { color: PIN.past, label: 'Last seen here', dashed: true },
    { color: PIN.warn, label: 'Moving or not rechecked', dashed: false },
  ]
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-[13px] text-muted">
      {rows.map((r) => (
        <span key={r.label} className="flex items-center gap-1.5">
          <span
            className={`size-2.5 rounded-full ${r.dashed ? 'border border-dashed bg-white' : ''}`}
            style={r.dashed ? { borderColor: r.color } : { background: r.color }}
          />
          {r.label}
        </span>
      ))}
    </div>
  )
}
