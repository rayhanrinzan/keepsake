import { useEffect, useId, useRef, useState } from 'react'
import { AccessibilityInfo, Platform, StyleSheet, useWindowDimensions, View } from 'react-native'
import type { ViewStyle } from 'react-native'
import Svg, { Defs, Ellipse, Path, RadialGradient, Stop } from 'react-native-svg'

const web = Platform.OS === 'web'

// Soft bendy shapes of colour around the voice circle. Each one wobbles, grows and shrinks at its
// own pace, so together they look like waves rising out of the circle.
const GLOWS = [
  { color: '#ffb066', peak: 0.6, r: 165, dx: 0, dy: 5, speed: 0.018, phase: 0 }, // light orange
  { color: '#ff5a3c', peak: 0.5, r: 125, dx: 40, dy: -26, speed: 0.026, phase: 1.3 }, // red
  { color: '#ffd23f', peak: 0.55, r: 128, dx: -40, dy: 26, speed: 0.022, phase: 2.6 }, // yellow
  { color: '#ffffff', peak: 0.42, r: 92, dx: 8, dy: 0, speed: 0.03, phase: 4.1 }, // white
]

// A closed blob around (x, y): the radius bends with the angle and with time, smoothed into curves.
function blob(x: number, y: number, r: number, a: number, seed: number) {
  const n = 8
  const pts = [...Array(n)].map((_, i) => {
    const th = (i / n) * Math.PI * 2
    const k = 1 + 0.3 * Math.sin(th * 2 + a + seed) + 0.18 * Math.sin(th * 3 - a * 1.4 + seed * 2)
    return [x + Math.cos(th) * r * k, y + Math.sin(th) * r * k * 0.85]
  })
  let d = `M${pts[0][0].toFixed(1)},${pts[0][1].toFixed(1)}`
  for (let i = 0; i < n; i++) {
    const [p0, p1, p2, p3] = [pts[(i - 1 + n) % n], pts[i], pts[(i + 1) % n], pts[(i + 2) % n]]
    const c1 = [p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6]
    const c2 = [p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6]
    d += `C${c1[0].toFixed(1)},${c1[1].toFixed(1)} ${c2[0].toFixed(1)},${c2[1].toFixed(1)} ${p2[0].toFixed(1)},${p2[1].toFixed(1)}`
  }
  return d + 'Z'
}

/**
 * The warm aura behind the voice circle: bendy glows of red, yellow, white and light orange that
 * grow, shrink and change shape through the glass and past its edge. They breathe slowly at rest
 * and swell with their voice (or Keepsake's) while it's talking.
 */
export function Aura({ height, center, energy, strength = 1 }: { height: number; center: number; energy: number; strength?: number }) {
  const { width: w } = useWindowDimensions()
  const [t, setT] = useState(0)
  // Unique gradient ids: on the web every screen's SVGs share one page, and a hidden screen's ids would win.
  const id = useId().replace(/:/g, '')
  const still = useRef(false)
  const swell = useRef(0)

  useEffect(() => {
    AccessibilityInfo.isReduceMotionEnabled().then(v => { still.current = v })
    const id = setInterval(() => setT(x => x + 1), 33)
    return () => clearInterval(id)
  }, [])

  // Ease toward the voice so the glows never jump.
  swell.current += (energy - swell.current) * 0.1
  const move = still.current ? 0 : 1

  return (
    <View style={[StyleSheet.absoluteFill, { height }]} pointerEvents="none">
      <Svg width={w} height={height}>
        <Defs>
          <RadialGradient id={`auraBase${id}`} cx="50%" cy="50%" r="50%">
            <Stop offset="0" stopColor="#ffd9a8" stopOpacity="0.45" />
            <Stop offset="1" stopColor="#ffd9a8" stopOpacity="0" />
          </RadialGradient>
        </Defs>
        <Ellipse opacity={strength} cx={w * 0.5} cy={center} rx={w * 0.75} ry={height * 0.34} fill={`url(#auraBase${id})`} />
      </Svg>
      {/* Blurred together on the web so the colours melt into each other. */}
      <View style={[StyleSheet.absoluteFill, web && s.blur]}>
        <Svg width={w} height={height}>
          <Defs>
            {GLOWS.map((g, i) => (
              <RadialGradient key={i} id={`glow${i}${id}`} cx="50%" cy="50%" r="50%">
                {/* A long, gentle fade so each colour spreads out rather than sitting in a lump. */}
                <Stop offset="0" stopColor={g.color} stopOpacity={g.peak} />
                <Stop offset="0.3" stopColor={g.color} stopOpacity={g.peak * 0.6} />
                <Stop offset="0.6" stopColor={g.color} stopOpacity={g.peak * 0.25} />
                <Stop offset="0.85" stopColor={g.color} stopOpacity={g.peak * 0.07} />
                <Stop offset="1" stopColor={g.color} stopOpacity="0" />
              </RadialGradient>
            ))}
          </Defs>
          {GLOWS.map((g, i) => {
            const a = t * g.speed * move + g.phase
            // In and out, a bit further when someone is talking.
            const r = g.r * (1 + 0.22 * Math.sin(a) + 0.06 * Math.sin(a * 2.3) + swell.current * 0.5)
            const x = w / 2 + g.dx + 12 * Math.sin(a * 0.7) * move
            const y = center + g.dy + 9 * Math.cos(a * 0.6) * move
            return <Path key={i} opacity={strength} d={blob(x, y, r, a, i * 1.7)} fill={`url(#glow${i}${id})`} />
          })}
        </Svg>
      </View>
    </View>
  )
}

const s = StyleSheet.create({
  blur: { filter: 'blur(15px)' } as ViewStyle,
})
