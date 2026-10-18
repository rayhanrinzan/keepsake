import { useEffect, useRef, useState } from 'react'
import { AccessibilityInfo, Animated, Easing, Platform, StyleSheet, View } from 'react-native'
import Svg, { Circle, Defs, RadialGradient, Stop } from 'react-native-svg'


// Soft color patches that drift around inside the blob, each on its own slow loop.
const PATCHES = [
  { color: '#ffd84d', r: 0.55, orbit: 0.3, ms: 6000, phase: 0 },
  { color: '#f7861d', r: 0.5, orbit: 0.32, ms: 8000, phase: 0.33 },
  { color: '#ff5f6d', r: 0.42, orbit: 0.3, ms: 10000, phase: 0.6 },
  { color: '#ffe3c4', r: 0.36, orbit: 0.26, ms: 7000, phase: 0.85 },
]

function useLoop(ms: number, still: boolean) {
  const v = useRef(new Animated.Value(0)).current
  useEffect(() => {
    if (still) return
    const a = Animated.loop(Animated.timing(v, { toValue: 1, duration: ms, easing: Easing.linear, useNativeDriver: Platform.OS !== 'web' }))
    a.start()
    return () => a.stop()
  }, [ms, still, v])
  return v
}

function Patch({ color, r, orbit, ms, phase, still, SIZE }: (typeof PATCHES)[number] & { still: boolean; SIZE: number }) {
  const t = useLoop(ms, still)
  const d = SIZE * r * 2
  const o = SIZE * orbit
  // Walks a wobbly circle: x and y follow sine curves sampled around the loop.
  const steps = [0, 0.25, 0.5, 0.75, 1]
  const at = (f: (a: number) => number) => steps.map(s => f((s + phase) * Math.PI * 2))
  const translateX = t.interpolate({ inputRange: steps, outputRange: at(a => Math.cos(a) * o) })
  const translateY = t.interpolate({ inputRange: steps, outputRange: at(a => Math.sin(a * 1.0) * o * 0.9) })
  const scale = t.interpolate({ inputRange: steps, outputRange: [1, 1.15, 0.92, 1.1, 1] })
  return (
    <Animated.View style={[s.patch, { width: d, height: d, marginLeft: -d / 2, marginTop: -d / 2, transform: [{ translateX }, { translateY }, { scale }] }]}>
      <Svg width={d} height={d}>
        <Defs>
          <RadialGradient id={`p${color}`} cx="50%" cy="50%" r="50%">
            <Stop offset="0" stopColor={color} stopOpacity="1" />
            <Stop offset="0.55" stopColor={color} stopOpacity="0.75" />
            <Stop offset="1" stopColor={color} stopOpacity="0" />
          </RadialGradient>
        </Defs>
        <Circle cx={d / 2} cy={d / 2} r={d / 2} fill={`url(#p${color})`} />
      </Svg>
    </Animated.View>
  )
}

/** A living gradient, like Siri: warm colors swirl inside while the whole blob bobs and breathes. */
export function Blob({ size: SIZE = 88 }: { size?: number }) {
  const [still, setStill] = useState(false)
  useEffect(() => { AccessibilityInfo.isReduceMotionEnabled().then(setStill).catch(() => {}) }, [])
  const breath = useLoop(3600, still)
  const translateY = breath.interpolate({ inputRange: [0, 0.5, 1], outputRange: [0, -4, 0] })
  const scale = breath.interpolate({ inputRange: [0, 0.5, 1], outputRange: [1, 1.06, 1] })

  return (
    <Animated.View style={{ transform: [{ translateY }, { scale }] }}>
      {/* Warm glow underneath so it lifts off the white page. */}
      <Svg width={SIZE * 1.8} height={SIZE * 1.8} style={{ position: 'absolute', left: -SIZE * 0.4, top: -SIZE * 0.3 }} pointerEvents="none">
        <Defs>
          <RadialGradient id="halo" cx="50%" cy="55%" r="50%">
            <Stop offset="0.45" stopColor="#f7941d" stopOpacity="0.28" />
            <Stop offset="1" stopColor="#f7941d" stopOpacity="0" />
          </RadialGradient>
        </Defs>
        <Circle cx={SIZE * 0.9} cy={SIZE * 0.9} r={SIZE * 0.9} fill="url(#halo)" />
      </Svg>
      <View style={{ width: SIZE, height: SIZE, borderRadius: SIZE / 2, overflow: 'hidden' }}>
        <View style={[StyleSheet.absoluteFill, { backgroundColor: '#ffbe5c' }]} />
        {PATCHES.map(p => <Patch key={p.color} {...p} still={still} SIZE={SIZE} />)}
        {/* Glossy highlight. */}
        <Svg width={SIZE} height={SIZE} style={StyleSheet.absoluteFill} pointerEvents="none">
          <Defs>
            <RadialGradient id="gloss" cx="32%" cy="26%" r="40%">
              <Stop offset="0" stopColor="#fff" stopOpacity="0.85" />
              <Stop offset="1" stopColor="#fff" stopOpacity="0" />
            </RadialGradient>
          </Defs>
          <Circle cx={SIZE / 2} cy={SIZE / 2} r={SIZE / 2} fill="url(#gloss)" />
        </Svg>
      </View>
    </Animated.View>
  )
}

const s = StyleSheet.create({
  patch: { position: 'absolute', left: '50%', top: '50%' },
})
