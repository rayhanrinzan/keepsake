import { useEffect, useId, useRef, useState } from 'react'
import { AccessibilityInfo, Platform, Pressable, StyleSheet, useWindowDimensions, View } from 'react-native'
import type { ViewStyle } from 'react-native'
import Svg, { Defs, Ellipse, LinearGradient, Path, RadialGradient, Stop } from 'react-native-svg'

const STEP = 5 // px between points along each thread
const web = Platform.OS === 'web'

const THREADS = 56

/**
 * The voice: one ribbon of fine light-orange and white threads in a sideways lens shape, pointed at
 * both ends. It rises and dips, pinches thin in some places and opens wide in others, and twists
 * as it goes, so the threads bunch up and spread out like a curved strip seen in 3D. While they
 * talk it swells and glows white to the beat of their voice; while Keepsake talks it opens and
 * lifts in soft swells with an orange glow. It drifts at rest. Tap it to talk.
 */
export function VoiceRibbon({ active, listening = false, energy, onPress, label, height = 210 }: { active: boolean; listening?: boolean; energy: number; onPress: () => void; label: string; height?: number }) {
  const { width: w } = useWindowDimensions()
  const id = useId().replace(/:/g, '')
  const [t, setT] = useState(0)
  const still = useRef(false)
  const amp = useRef(0)
  const loud = useRef(0)

  useEffect(() => {
    AccessibilityInfo.isReduceMotionEnabled().then(v => { still.current = v })
    const i = setInterval(() => setT(x => x + 1), 33)
    return () => clearInterval(i)
  }, [])

  // Ease toward the voice so nothing jumps.
  amp.current += ((active ? 0.75 : 0.62) - amp.current) * 0.1
  loud.current += ((active ? 0.15 + energy * (listening ? 1.2 : 0.9) : 0) - loud.current) * (listening ? 0.25 : 0.12)
  const tt = still.current ? 0 : t
  const mid = height / 2
  const glow = listening ? '#ffffff' : '#ff8a2a'
  const a = amp.current
  const v = still.current ? 0 : loud.current // how hard the voice is shaking it

  const xs: number[] = []
  for (let x = -10; x <= w + 10; x += STEP) xs.push(x)

  const paths: { d: string; f: number }[] = []
  for (let k = 0; k < THREADS; k++) {
    const f = (k / (THREADS - 1)) * 2 - 1 // -1 at one edge of the strip, 1 at the other
    let d = ''
    for (const x of xs) {
      const u = x / w
      // The whole ribbon sits in a sideways lens, ( ) turned on its side: widest in the middle,
      // narrowing to sharp points at both ends.
      const lens = Math.pow(Math.max(0, Math.sin(Math.PI * u)), 1.1)
      // Where the ribbon's middle is: big slow rises and dips.
      const centre = Math.sin(u * 4.4 - tt * 0.035) * 0.55 + Math.sin(u * 9 + tt * 0.025 + 1.3) * 0.25 + Math.sin(u * 1.7 + tt * 0.015) * 0.2
      // How wide it is here: from a thin pinch to wide open.
      const wide = 0.35 + 0.65 * Math.pow(0.5 + 0.5 * Math.sin(u * 5.3 + tt * 0.03 + 0.8), 1.6)
      // How far it has turned: flat-on shows its full width, edge-on squeezes the threads together.
      const turn = u * 6.5 - tt * 0.045
      // A curved strip, so the threads crowd toward one edge as it turns.
      const off = f * Math.sin(turn) + 0.35 * Math.cos(turn) * (1 - f * f)
      const near = Math.exp(-Math.pow((u - 0.5) / (listening ? 0.3 : 0.22), 2))
      let y
      if (listening) {
        // Their voice: the same ribbon simply swells bigger and wider with each beat of their voice.
        const beat = 1 + v * 0.9 * (0.5 + 0.5 * near)
        y = mid + height * lens * beat * a * (0.3 * centre + 0.34 * wide * off)
      } else {
        // Keepsake's voice: the middle breathes open and lifts in a few soft rolling swells.
        const swell = v * near * (0.6 + 0.4 * Math.sin(u * 13 - tt * 0.22))
        const lift = v * near * (Math.sin(u * 9 - tt * 0.18) * 0.6 + Math.sin(u * 15 + tt * 0.13) * 0.4)
        y = mid + height * lens * (a * (0.3 * centre + 0.34 * (wide + swell * 0.9) * off) + 0.12 * lift)
      }
      d += `${d ? 'L' : 'M'}${x},${y.toFixed(1)}`
    }
    paths.push({ d, f })
  }

  return (
    <Pressable onPress={onPress} style={[s.noRing, { width: w, height }]} accessibilityRole="button" accessibilityLabel={label}>
      {/* A white glow beating with their voice, blurred on the web. None behind Keepsake's voice. */}
      <View style={[StyleSheet.absoluteFill, web && s.soft]}>
        <Svg width={w} height={height}>
          <Defs>
            <RadialGradient id={`glow${id}`} cx="50%" cy="50%" r="50%">
              <Stop offset="0" stopColor={glow} stopOpacity="1" />
              <Stop offset="0.6" stopColor={glow} stopOpacity="0.45" />
              <Stop offset="1" stopColor={glow} stopOpacity="0" />
            </RadialGradient>
          </Defs>
          <Ellipse cx={w / 2} cy={mid} rx={w * 0.4} ry={height * 0.3} fill={`url(#glow${id})`} opacity={listening ? Math.min(0.45, loud.current * 0.5) : 0} />
        </Svg>
      </View>
      <View style={StyleSheet.absoluteFill}>
        <Svg width={w} height={height}>
          <Defs>
            <LinearGradient id={`thread${id}`} x1="0" y1="0" x2={w} y2="0" gradientUnits="userSpaceOnUse">
              <Stop offset="0" stopColor="#ffb878" stopOpacity="0.5" />
              <Stop offset="0.35" stopColor="#ffd2a6" />
              <Stop offset="0.6" stopColor="#ffffff" />
              <Stop offset="0.85" stopColor="#ffc28a" />
              <Stop offset="1" stopColor="#ff9f55" stopOpacity="0.6" />
            </LinearGradient>
          </Defs>
          {/* Edge threads a touch brighter than the middle ones, like light catching the fold. */}
          {paths.map((p, k) => <Path key={k} d={p.d} stroke={`url(#thread${id})`} strokeWidth={0.8} strokeOpacity={0.45 + 0.35 * Math.abs(p.f)} fill="none" />)}
        </Svg>
      </View>
    </Pressable>
  )
}

const s = StyleSheet.create({
  noRing: { outlineStyle: 'none' } as unknown as ViewStyle, // no browser focus box around it
  soft: { filter: 'blur(18px)' } as ViewStyle,
})
