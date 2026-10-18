import { useEffect, useId, useMemo, useRef, useState } from 'react'
import { AccessibilityInfo, Animated, Easing, Platform, Pressable, StyleSheet, useWindowDimensions } from 'react-native'
import { useSafeAreaInsets } from 'react-native-safe-area-context'
import Svg, { ClipPath, Defs, Ellipse, G, Polygon, Rect, Use } from 'react-native-svg'
import { P } from '../lib/theme'
import { T } from './ui'

const COLS = 7
const ROWS = 5 // 7 × 5 cells, two facets each: 70 creased facets
const FRAME_MS = 1000 / 12 // stop motion: each pose is held, then jumps to the next
const FRAMES = 18 // popping open from the first frame, then 4 settling flat
const LOOSEN = 1 / FRAMES
const SETTLE = 14 / FRAMES
const POP = 0.16 // how long one section takes to swing open, as a share of the whole
const BACK = '#f7f7f7' // the back of the paper is white
const FACE = '#000000' // and the front is black, like the home page it opens into
const native = Platform.OS !== 'web'
const ICON_W = 52
const ICON_H = 29
const GAP = 12

type Pt = [number, number]
type Vertex = { flat: Pt; ball: Pt; start: number }
type Facet = { a: number; b: number; c: number; start: number; ridge: number }

const easeOut = (t: number) => 1 - Math.pow(1 - t, 3)
const clamp01 = (t: number) => Math.min(1, Math.max(0, t))

/** Random but repeatable, so the ball looks the same every time. */
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
 * The sheet as irregular creased facets. Flat, they tile the page. Crumpled, every corner is
 * pulled into a lumpy ball with the sheet's edge wrapped around the outside. A few random "pull"
 * points decide when each part pops open, so it opens in clumps.
 */
function buildMesh(w: number, h: number) {
  const rand = rng(11)
  const r = Math.min(w, h) * 0.16
  const xs = spacing(COLS)
  const ys = spacing(ROWS)
  const pulls = [0, 1, 2, 3].map(n => ({ at: [rand(), rand()], start: n * 0.1 + rand() * 0.04 }))
  const verts: Vertex[] = []
  for (let j = 0; j <= ROWS; j++) {
    for (let i = 0; i <= COLS; i++) {
      const inside = i > 0 && i < COLS && j > 0 && j < ROWS
      // Inside points are knocked off the grid so the creases run at odd angles.
      const u = xs[i] + (inside ? ((rand() - 0.5) * 0.6 * (xs[i + 1] - xs[i - 1])) / 2 : 0)
      const v = ys[j] + (inside ? ((rand() - 0.5) * 0.6 * (ys[j + 1] - ys[j - 1])) / 2 : 0)
      const x = u * 2 - 1
      const y = v * 2 - 1
      const edge = Math.max(Math.abs(x), Math.abs(y))
      const angle = Math.atan2(y, x) + (rand() - 0.5) * 0.5
      const dist = r * (0.3 + 0.7 * edge) * (0.82 + rand() * 0.3)
      const near = pulls.reduce((m, p) => Math.min(m, p.start + Math.hypot(u - p.at[0], v - p.at[1]) * 0.3), Infinity)
      verts.push({ flat: [u * w, v * h], ball: [w * 0.5 + Math.cos(angle) * dist, h * 0.45 + Math.sin(angle) * dist], start: Math.min(near, SETTLE - POP) })
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
        facets.push({ a, b, c, start, ridge: (rand() - 0.5) * 1.2 })
      }
    }
  }
  // Sections that open last sit on the outside of the ball, so they draw on top.
  facets.sort((f, g) => f.start - g.start)
  return { verts, facets, r }
}

/** The affine transform that carries triangle (a, b, c) onto (A, B, C), as [a b c d e f]. */
function affine([a, b, c]: Pt[], [A, B, C]: Pt[]) {
  const d = (b[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (b[1] - a[1])
  const m11 = ((B[0] - A[0]) * (c[1] - a[1]) - (C[0] - A[0]) * (b[1] - a[1])) / d
  const m12 = ((C[0] - A[0]) * (b[0] - a[0]) - (B[0] - A[0]) * (c[0] - a[0])) / d
  const m21 = ((B[1] - A[1]) * (c[1] - a[1]) - (C[1] - A[1]) * (b[1] - a[1])) / d
  const m22 = ((C[1] - A[1]) * (b[0] - a[0]) - (B[1] - A[1]) * (c[0] - a[0])) / d
  return [m11, m21, m12, m22, A[0] - m11 * a[0] - m12 * a[1], A[1] - m21 * a[0] - m22 * a[1]]
}

const pts = (list: Pt[]) => list.map(p => `${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(' ')

/**
 * The opening: on a white page, a crumpled ball of black paper, white on the back, pops open
 * in stop-motion clumps and is pressed flat into the black page. The logo settles in, the word
 * squeezes into the key, and the key flies to the top left corner where home keeps it. Tap to skip.
 */
export function Unfold({ onDone }: { onDone: () => void }) {
  const { width: w, height: h } = useWindowDimensions()
  const id = useId().replace(/:/g, '')
  const mesh = useMemo(() => buildMesh(w, h), [w, h])
  const [frame, setFrame] = useState(0)
  const inset = useSafeAreaInsets()
  const [tw, setTw] = useState(150) // the word's width, measured once it's laid out
  const logo = useRef(new Animated.Value(0)).current
  const squeeze = useRef(new Animated.Value(0)).current
  const fly = useRef(new Animated.Value(0)).current
  const fade = useRef(new Animated.Value(1)).current
  const done = useRef(false)

  const go = () => {
    if (done.current) return
    done.current = true
    Animated.timing(fade, { toValue: 0, duration: 300, useNativeDriver: native }).start(onDone)
  }

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout>
    let tick: ReturnType<typeof setInterval> | undefined
    AccessibilityInfo.isReduceMotionEnabled().then(still => {
      if (still) {
        setFrame(FRAMES)
        logo.setValue(1)
        timer = setTimeout(() => { squeeze.setValue(1); fly.setValue(1); go() }, 1500)
        return
      }
      timer = setTimeout(() => {
        tick = setInterval(() => setFrame(f => {
          if (f + 1 >= FRAMES) {
            clearInterval(tick)
            // The full logo, then the word squeezes into the key and the key flies to the corner.
            Animated.sequence([
              Animated.timing(logo, { toValue: 1, duration: 500, useNativeDriver: native }),
              Animated.delay(550),
              Animated.timing(squeeze, { toValue: 1, duration: 450, easing: Easing.in(Easing.cubic), useNativeDriver: native }),
              Animated.timing(fly, { toValue: 1, duration: 650, easing: Easing.inOut(Easing.cubic), useNativeDriver: native }),
            ]).start(() => go())
          }
          return Math.min(FRAMES, f + 1)
        }), FRAME_MS)
      }, 500) // a moment to see the ball before it opens
    })
    return () => { clearTimeout(timer); clearInterval(tick) }
  }, [])

  const { verts, facets, r } = mesh
  const iconLeft = (w - (ICON_W + GAP + tw)) / 2
  const iconTop = h / 2 - ICON_H / 2
  const t = frame / FRAMES
  // Each point barely loosens, pops open fast when its section's turn comes, then everything is
  // pressed flat over the last few frames.
  const settle = clamp01((t - SETTLE) / (1 - SETTLE))
  const pos = verts.map((v): [number, number, number] => {
    const loose = 0.06 * clamp01(t / LOOSEN)
    const pop = easeOut(clamp01((t - v.start) / POP)) * 0.92
    const k = Math.max(loose, pop) + (1 - Math.max(loose, pop)) * settle
    return [v.ball[0] + (v.flat[0] - v.ball[0]) * k, v.ball[1] + (v.flat[1] - v.ball[1]) * k, k]
  })
  // A tiny hand-made wobble on every held frame, none on the last.
  const wob = rng(frame + 5)
  const jitter = frame > 0 && frame < FRAMES ? `rotate(${((wob() - 0.5) * 1.4).toFixed(2)} ${w / 2} ${h / 2}) translate(${((wob() - 0.5) * 3).toFixed(1)} ${((wob() - 0.5) * 3).toFixed(1)})` : undefined
  const creases = 0.25 * (1 - settle)

  return (
    <Animated.View style={[StyleSheet.absoluteFill, { opacity: fade, zIndex: 10 }]}>
      <Pressable onPress={go} accessibilityLabel="Skip the intro" style={s.page}>
        <Svg width={w} height={h} style={StyleSheet.absoluteFill}>
          <Defs>
            <G id={`face${id}`}>
              <Rect x={0} y={0} width={w} height={h} fill={FACE} />
            </G>
            {facets.map((f, k) => {
              // Each facet's own shape on the flat sheet, grown a pixel to hide the seams.
              const tri = [verts[f.a].flat, verts[f.b].flat, verts[f.c].flat]
              const cx = (tri[0][0] + tri[1][0] + tri[2][0]) / 3
              const cy = (tri[0][1] + tri[1][1] + tri[2][1]) / 3
              const grown = tri.map(([x, y]): Pt => { const l = Math.hypot(x - cx, y - cy); return [x + (x - cx) / l, y + (y - cy) / l] })
              return <ClipPath key={k} id={`facet${k}${id}`}><Polygon points={pts(grown)} /></ClipPath>
            })}
          </Defs>
          {/* A soft shadow under the white ball so it stands off the white page, gone once it opens. */}
          <Ellipse cx={w / 2} cy={h * 0.45 + r * 0.95} rx={r * 1.05} ry={r * 0.22} fill="#000000" opacity={0.12 * clamp01(1 - t * 2.5)} />
          <G transform={jitter}>
            {facets.map((f, k) => {
              const [a, b, c] = [pos[f.a], pos[f.b], pos[f.c]]
              const tri = [verts[f.a].flat, verts[f.b].flat, verts[f.c].flat]
              const m = affine(tri, [[a[0], a[1]], [b[0], b[1]], [c[0], c[1]]])
              const crumple = 1 - (a[2] + b[2] + c[2]) / 3
              // Turned over (mirrored), or still balled up on the outside: we see the white back.
              const back = m[0] * m[3] - m[1] * m[2] < 0 || crumple > 0.55
              // Light from the top left on the ball, plus the facet's own ridge or valley.
              const bx = ((a[0] + b[0] + c[0]) / 3 - w * 0.5) / r
              const by = ((a[1] + b[1] + c[1]) / 3 - h * 0.45) / r
              const ball = Math.max(0, 1 - Math.hypot(bx, by) / 3)
              const light = f.ridge + ball * (-(bx * 0.35 + by * 0.4) - 0.25 * (bx * bx + by * by) + 0.2)
              const alpha = Math.min(0.6, Math.abs(light) * crumple * (light < 0 ? 0.8 : 0.45))
              return (
                <G key={k} transform={`matrix(${m.map(n => n.toFixed(4)).join(' ')})`}>
                  {back
                    ? <Polygon points={pts(tri)} fill={BACK} />
                    : <Use href={`#face${id}`} clipPath={`url(#facet${k}${id})`} />}
                  {alpha > 0.01 && <Polygon points={pts(tri)} fill={light < 0 ? '#000000' : '#ffffff'} fillOpacity={alpha} />}
                  {creases > 0.01 && <Polygon points={pts(tri)} fill="none" stroke={back ? '#b5b5b5' : '#ffffff'} strokeOpacity={creases} strokeWidth={0.8} vectorEffect="non-scaling-stroke" />}
                </G>
              )
            })}
          </G>
        </Svg>
        {/* The key starts centred beside the word and ends exactly where home shows it, top left. */}
        <Animated.Image source={require('../../assets/inside-icon.png')} resizeMode="contain" style={[s.icon, {
          left: iconLeft, top: iconTop, opacity: logo,
          transform: [
            { translateX: fly.interpolate({ inputRange: [0, 1], outputRange: [0, 22 - iconLeft - (ICON_W - 40) / 2] }) },
            { translateY: Animated.add(logo.interpolate({ inputRange: [0, 1], outputRange: [12, 0] }), fly.interpolate({ inputRange: [0, 1], outputRange: [0, inset.top + 16 + 11 - (iconTop + ICON_H / 2)] })) },
            { scale: fly.interpolate({ inputRange: [0, 1], outputRange: [1, 40 / ICON_W] }) },
          ],
        }]} />
        <Animated.View onLayout={e => setTw(e.nativeEvent.layout.width)} style={[s.word, {
          left: iconLeft + ICON_W + GAP, top: iconTop - 6, transformOrigin: 'left',
          opacity: Animated.multiply(logo, squeeze.interpolate({ inputRange: [0, 0.7, 1], outputRange: [1, 0.6, 0] })),
          transform: [
            { translateY: logo.interpolate({ inputRange: [0, 1], outputRange: [12, 0] }) },
            { translateX: squeeze.interpolate({ inputRange: [0, 1], outputRange: [0, -GAP - 6] }) },
            { scaleX: squeeze.interpolate({ inputRange: [0, 1], outputRange: [1, 0.05] }) },
          ],
        }]}>
          <T size={30} weight="regular" color={P.line}>keepsake</T>
        </Animated.View>
      </Pressable>
    </Animated.View>
  )
}

const s = StyleSheet.create({
  page: { flex: 1, backgroundColor: '#ffffff' },
  icon: { position: 'absolute', width: ICON_W, height: ICON_H },
  word: { position: 'absolute' },
})
