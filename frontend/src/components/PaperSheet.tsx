import { useLayoutEffect, useRef, useState, type ReactNode } from 'react'

const COLS = 7
const ROWS = 5 // 7 × 5 cells, two facets each: 70 creased facets
const FRAME_MS = 1000 / 12 // stop motion: each pose is held, then jumps to the next
const FRAMES = 18 // popping open from the first frame, then 4 settling flat
const LOOSEN = 1 / FRAMES
const SETTLE = 14 / FRAMES
const POP = 0.16 // how long one section takes to swing open, as a share of the whole
let played = false // once per page load, not every time you come back to the Map tab

type Pt = [number, number]
type Vertex = { flat: Pt; ball: Pt; start: number }
type Facet = { a: number; b: number; c: number; start: number; ridge: number }

const easeOut = (t: number) => 1 - Math.pow(1 - t, 3)
const clamp01 = (t: number) => Math.min(1, Math.max(0, t))

/** Random but repeatable, so the ball looks the same on every load. */
function rng(seed: number) {
  return () => {
    seed = (seed * 16807) % 2147483647
    return seed / 2147483647
  }
}

/** Grid line positions that bunch up toward the edges: big facets in the middle, small at the edges. */
function spacing(n: number) {
  return Array.from({ length: n + 1 }, (_, i) => {
    const x = (i / n) * 2 - 1
    return 0.5 + 0.5 * Math.sign(x) * Math.pow(Math.abs(x), 0.7)
  })
}

/**
 * The sheet as irregular creased facets. Flat, they tile the sheet with a straight outline.
 * Crumpled, every corner is pulled into a lumpy ball with the sheet's edge wrapped around the
 * outside. A few random "pull" points decide when each part pops open, so it opens in clumps.
 */
function buildMesh(w: number, h: number) {
  const rand = rng(11)
  const r = Math.min(w, h) * 0.14
  const xs = spacing(COLS)
  const ys = spacing(ROWS)
  const pulls = [0, 1, 2, 3].map((n) => ({ at: [rand(), rand()], start: n * 0.1 + rand() * 0.04 }))
  const verts: Vertex[] = []
  for (let j = 0; j <= ROWS; j++) {
    for (let i = 0; i <= COLS; i++) {
      const inside = i > 0 && i < COLS && j > 0 && j < ROWS
      // Inside points are knocked off the grid so the creases run at odd angles.
      const u = xs[i] + (inside ? (rand() - 0.5) * 0.6 * (xs[i + 1] - xs[i - 1]) / 2 : 0)
      const v = ys[j] + (inside ? (rand() - 0.5) * 0.6 * (ys[j + 1] - ys[j - 1]) / 2 : 0)
      const x = u * 2 - 1
      const y = v * 2 - 1
      const edge = Math.max(Math.abs(x), Math.abs(y))
      const angle = Math.atan2(y, x) + (rand() - 0.5) * 0.5
      const dist = r * (0.3 + 0.7 * edge) * (0.82 + rand() * 0.3)
      const near = pulls.reduce((m, p) => Math.min(m, p.start + Math.hypot(u - p.at[0], v - p.at[1]) * 0.3), Infinity)
      verts.push({
        flat: [u * w, v * h],
        ball: [w * 0.5 + Math.cos(angle) * dist, h * 0.48 + Math.sin(angle) * dist],
        start: Math.min(near, SETTLE - POP),
      })
    }
  }
  const facets: Facet[] = []
  const at = (i: number, j: number) => j * (COLS + 1) + i
  for (let j = 0; j < ROWS; j++) {
    for (let i = 0; i < COLS; i++) {
      const [p, q, s, t] = [at(i, j), at(i + 1, j), at(i + 1, j + 1), at(i, j + 1)]
      const tris = rand() > 0.5 ? [[p, q, s], [p, s, t]] : [[p, q, t], [q, s, t]]
      for (const [a, b, c] of tris) {
        const start = (verts[a].start + verts[b].start + verts[c].start) / 3
        // Ridge (lit) or valley (shadow): neighbours differ, so creases read as crisp edges.
        facets.push({ a, b, c, start, ridge: (rand() - 0.5) * 1.2 })
      }
    }
  }
  // Sections that open last sit on the outside of the ball, so they draw on top.
  facets.sort((f, g) => f.start - g.start)
  return { verts, facets, r }
}

/** The affine transform that carries triangle (a, b, c) onto (A, B, C), as canvas [a b c d e f]. */
function affine([a, b, c]: Pt[], [A, B, C]: Pt[]) {
  const d = (b[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (b[1] - a[1])
  const m11 = ((B[0] - A[0]) * (c[1] - a[1]) - (C[0] - A[0]) * (b[1] - a[1])) / d
  const m12 = ((C[0] - A[0]) * (b[0] - a[0]) - (B[0] - A[0]) * (c[0] - a[0])) / d
  const m21 = ((B[1] - A[1]) * (c[1] - a[1]) - (C[1] - A[1]) * (b[1] - a[1])) / d
  const m22 = ((C[1] - A[1]) * (b[0] - a[0]) - (B[1] - A[1]) * (c[0] - a[0])) / d
  return [m11, m21, m12, m22, A[0] - m11 * a[0] - m12 * a[1], A[1] - m21 * a[0] - m22 * a[1]]
}

/** The blueprint paper itself, drawn once, so the grid is on the sheet the whole time it unfolds. */
function paperTexture(w: number, h: number, dpr: number) {
  const c = document.createElement('canvas')
  c.width = w * dpr
  c.height = h * dpr
  const g = c.getContext('2d')!
  g.scale(dpr, dpr)
  const bg = g.createRadialGradient(w * 0.55, h * 0.45, 0, w * 0.55, h * 0.45, Math.hypot(w, h) * 0.6)
  bg.addColorStop(0, '#e4f2ff')
  bg.addColorStop(0.6, '#d2e8fd')
  bg.addColorStop(1, '#bdd9f6')
  g.fillStyle = bg
  g.fillRect(0, 0, w, h)
  g.lineWidth = 1
  for (const [step, alpha] of [[20, 0.22], [100, 0.4]]) {
    g.strokeStyle = `rgb(60 130 215 / ${alpha})`
    g.stroke(new Path2D(gridPath(w, h, step)))
  }
  return c
}

/**
 * A sheet of blueprint paper with torn edges. When it first appears it's a crumpled ball that
 * unfolds into the sheet on its own; then the drawing and anything else inside fade in.
 */
export function PaperSheet({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(() => played || matchMedia('(prefers-reduced-motion: reduce)').matches)
  const boxRef = useRef<HTMLDivElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useLayoutEffect(() => {
    const canvas = canvasRef.current
    if (open || !boxRef.current || !canvas) return
    const { width: w, height: h } = boxRef.current.getBoundingClientRect()
    const dpr = Math.min(2, devicePixelRatio || 1)
    canvas.width = w * dpr
    canvas.height = h * dpr
    const g = canvas.getContext('2d')!
    const tex = paperTexture(w, h, dpr)
    const mesh = buildMesh(w, h)
    const { verts, facets } = mesh
    let raf = 0
    const start = performance.now()
    let shown = -1
    const wobble = rng(5)
    const step = (now: number) => {
      const frame = Math.min(FRAMES, Math.floor((now - start) / FRAME_MS))
      if (frame === shown) {
        raf = requestAnimationFrame(step)
        return
      }
      shown = frame
      const t = frame / FRAMES
      // Each point: barely loosens, pops open fast when its section's turn comes, then everything
      // is pressed flat over the last few frames.
      const settle = clamp01((t - SETTLE) / (1 - SETTLE))
      const pos = verts.map((v): [number, number, number] => {
        const loose = 0.06 * clamp01(t / LOOSEN)
        const pop = easeOut(clamp01((t - v.start) / POP)) * 0.92
        const k = Math.max(loose, pop) + (1 - Math.max(loose, pop)) * settle
        return [v.ball[0] + (v.flat[0] - v.ball[0]) * k, v.ball[1] + (v.flat[1] - v.ball[1]) * k, k]
      })
      g.setTransform(1, 0, 0, 1, 0, 0)
      g.clearRect(0, 0, canvas.width, canvas.height)
      // A tiny hand-made wobble on every held frame, none on the last.
      const jx = frame < FRAMES ? (wobble() - 0.5) * 3 : 0
      const jy = frame < FRAMES ? (wobble() - 0.5) * 3 : 0
      const jr = frame < FRAMES ? ((wobble() - 0.5) * 1.4 * Math.PI) / 180 : 0
      const base = new DOMMatrix().translate(w / 2 + jx, h / 2 + jy).rotate((jr * 180) / Math.PI).translate(-w / 2, -h / 2)
      const creases = 0.22 * (1 - settle)
      for (const f of facets) {
        const [a, b, c] = [pos[f.a], pos[f.b], pos[f.c]]
        const [fa, fb, fc] = [verts[f.a].flat, verts[f.b].flat, verts[f.c].flat]
        // Map this facet of the flat texture onto where it is now; the clip is grown 1px to hide seams.
        const [m11, m21, m12, m22, e, f2] = affine([fa, fb, fc], [[a[0], a[1]], [b[0], b[1]], [c[0], c[1]]])
        const m = base.multiply(new DOMMatrix([m11, m21, m12, m22, e, f2]))
        g.setTransform(dpr * m.a, dpr * m.b, dpr * m.c, dpr * m.d, dpr * m.e, dpr * m.f)
        g.save()
        g.beginPath()
        const cx = (fa[0] + fb[0] + fc[0]) / 3
        const cy = (fa[1] + fb[1] + fc[1]) / 3
        for (const [x, y] of [fa, fb, fc]) {
          const len = Math.hypot(x - cx, y - cy)
          g.lineTo(x + (x - cx) / len, y + (y - cy) / len)
        }
        g.closePath()
        g.clip()
        g.drawImage(tex, 0, 0, w, h)
        g.restore()
        // Shading on the exact facet: ball light from the top left, a darker rim, and the facet's
        // own ridge or valley, all fading as it flattens.
        const crumple = 1 - (a[2] + b[2] + c[2]) / 3
        const bx = ((a[0] + b[0] + c[0]) / 3 - w * 0.5) / mesh.r
        const by = ((a[1] + b[1] + c[1]) / 3 - h * 0.48) / mesh.r
        const ball = Math.max(0, 1 - Math.hypot(bx, by) / 3) // only reads as a ball while it's small
        const light = f.ridge + ball * (-(bx * 0.35 + by * 0.4) - 0.25 * (bx * bx + by * by) + 0.2)
        const alpha = Math.min(0.7, Math.abs(light) * crumple * (light < 0 ? 0.85 : 0.5))
        g.beginPath()
        g.moveTo(fa[0], fa[1])
        g.lineTo(fb[0], fb[1])
        g.lineTo(fc[0], fc[1])
        g.closePath()
        if (alpha > 0.01) {
          g.globalAlpha = alpha
          g.fillStyle = light < 0 ? '#2a5a9a' : '#ffffff'
          g.fill()
        }
        // Faint crease lines that linger after it opens, then fade as it lies flat.
        if (creases > 0.01) {
          g.globalAlpha = creases
          g.strokeStyle = light < 0 ? '#5b8fcf' : '#ffffff'
          g.lineWidth = 1 / Math.max(0.2, Math.sqrt(Math.abs(m.a * m.d - m.b * m.c)))
          g.stroke()
        }
        g.globalAlpha = 1
      }
      if (t < 1) raf = requestAnimationFrame(step)
      else {
        played = true
        setOpen(true)
      }
    }
    raf = requestAnimationFrame(step)
    return () => cancelAnimationFrame(raf)
  }, [open])

  return (
    <div ref={boxRef} className="relative size-full">
      <div className={`sheet ${open ? 'open' : ''}`}>
        <div className="sheet-paper" aria-hidden />
        <div className="sheet-grid" aria-hidden />
        <div className="sheet-content">{children}</div>
      </div>

      {!open && <canvas ref={canvasRef} className="sheet-unfold" aria-hidden />}

      {/* Torn edge for the sheet. fray-edge only moves the outline, so the grid inside stays straight. */}
      <svg width="0" height="0" className="absolute" aria-hidden>
        <filter id="fray" x="-5%" y="-5%" width="110%" height="110%">
          <feTurbulence type="fractalNoise" baseFrequency="0.035 0.05" numOctaves="4" seed="7" result="noise" />
          <feDisplacementMap in="SourceGraphic" in2="noise" scale="6" xChannelSelector="R" yChannelSelector="G" />
        </filter>
        <filter id="fray-edge" x="-5%" y="-5%" width="110%" height="110%">
          <feTurbulence type="fractalNoise" baseFrequency="0.035 0.05" numOctaves="4" seed="7" result="noise" />
          <feDisplacementMap in="SourceGraphic" in2="noise" scale="6" xChannelSelector="R" yChannelSelector="G" result="torn" />
          <feComposite in="SourceGraphic" in2="torn" operator="in" result="crisp" />
          <feMerge><feMergeNode in="torn" /><feMergeNode in="crisp" /></feMerge>
        </filter>
      </svg>
    </div>
  )
}

/** Grid lines every `step` px, inset like the sheet's own grid. */
function gridPath(w: number, h: number, step: number) {
  let d = ''
  for (let x = 16; x <= w - 16; x += step) d += `M${x} 16V${h - 16}`
  for (let y = 16; y <= h - 16; y += step) d += `M16 ${y}H${w - 16}`
  return d
}
