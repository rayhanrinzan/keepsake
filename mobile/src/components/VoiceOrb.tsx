import { BlurView } from 'expo-blur'
import { useEffect, useId, useRef, useState } from 'react'
import { Animated, Easing, Platform, Pressable, StyleSheet, View } from 'react-native'
import type { ViewStyle } from 'react-native'
import Svg, { Circle, Defs, Ellipse, LinearGradient, RadialGradient, Rect, Stop } from 'react-native-svg'

const native = Platform.OS !== 'web'

/**
 * The glass circle they tap to talk. It stays still; while it's listening or
 * speaking the circle itself pulses with a soft light in a slow heartbeat, over and over. On hover it
 * frosts over into whiter, glassier glass, and brightens again when pressed.
 */
export function VoiceOrb({ size = 132, active, level, onPress, label }: { size?: number; active: boolean; level: number; onPress: () => void; label: string }) {
  const id = useId().replace(/:/g, '')
  const beat = useRef(new Animated.Value(0)).current
  const hover = useRef(new Animated.Value(0)).current
  const press = useRef(new Animated.Value(0)).current
  const [hovered, setHovered] = useState(false)
  const lift = (on: boolean) => {
    setHovered(on)
    Animated.spring(hover, { toValue: on ? 1 : 0, useNativeDriver: native, speed: 18, bounciness: 6 }).start()
  }
  const push = (on: boolean) => Animated.timing(press, { toValue: on ? 1 : 0, duration: on ? 80 : 260, useNativeDriver: native }).start()

  // Lub-dub, rest, repeat.
  useEffect(() => {
    if (!active) {
      Animated.timing(beat, { toValue: 0, duration: 400, useNativeDriver: native }).start()
      return
    }
    const t = (toValue: number, duration: number) => Animated.timing(beat, { toValue, duration, easing: Easing.out(Easing.quad), useNativeDriver: native })
    const loop = Animated.loop(Animated.sequence([t(1, 160), t(0.45, 180), t(0.9, 150), t(0.15, 650), Animated.delay(350)]))
    loop.start()
    return () => loop.stop()
  }, [active])

  const bars = [0.45, 0.85, 1, 0.6].map((b, i) => Math.max(0.25, active ? Math.min(1, b * (0.55 + level * 1.6) * (i % 2 ? 1 : 0.85)) : b))

  return (
    <Pressable onPress={onPress} onHoverIn={() => lift(true)} onHoverOut={() => lift(false)} onPressIn={() => push(true)} onPressOut={() => push(false)} style={s.noRing} accessibilityRole="button" accessibilityLabel={label}>
      {/* Swells a little on hover, and with each heartbeat. */}
      <Animated.View style={[s.orb, { width: size, height: size, borderRadius: size / 2, transform: [{ scale: Animated.add(hover.interpolate({ inputRange: [0, 1], outputRange: [1, 1.03] }), beat.interpolate({ inputRange: [0, 1], outputRange: [0, 0.02] })) }] }]}>
        <BlurView intensity={8} tint="light" style={[StyleSheet.absoluteFill, Platform.OS === 'web' && s.webBlur]} />
        {/* On hover the glass frosts over: a stronger blur, light pooling along the top, and a highlight. */}
        <Animated.View style={[StyleSheet.absoluteFill, { opacity: hover }]} pointerEvents="none">
          <BlurView intensity={28} tint="light" style={[StyleSheet.absoluteFill, Platform.OS === 'web' && s.webFrost]} />
          <Svg width={size} height={size} style={StyleSheet.absoluteFill}>
            <Defs>
              <LinearGradient id={`orbSheen${id}`} x1="0" y1="0" x2="0" y2="1">
                <Stop offset="0" stopColor="#ffffff" stopOpacity="0.5" />
                <Stop offset="0.5" stopColor="#ffffff" stopOpacity="0.05" />
                <Stop offset="1" stopColor="#ffffff" stopOpacity="0.2" />
              </LinearGradient>
            </Defs>
            <Circle cx={size / 2} cy={size / 2} r={size / 2 - 1} fill={`url(#orbSheen${id})`} />
            <Ellipse cx={size * 0.36} cy={size * 0.22} rx={size * 0.18} ry={size * 0.07} fill="#ffffff" fillOpacity={0.35} transform={`rotate(-25 ${size * 0.36} ${size * 0.22})`} />
            <Circle cx={size / 2} cy={size / 2} r={size / 2 - 4} fill="none" stroke="#ffffff" strokeOpacity={0.35} strokeWidth={1} />
          </Svg>
        </Animated.View>
        {/* Only the circle itself lights up: whiter on hover and tap, and softly on each beat. */}
        <Animated.View style={[StyleSheet.absoluteFill, { backgroundColor: '#ffffff', opacity: Animated.add(Animated.add(beat.interpolate({ inputRange: [0, 1], outputRange: [0, 0.14] }), hover.interpolate({ inputRange: [0, 1], outputRange: [0, 0.12] })), press.interpolate({ inputRange: [0, 1], outputRange: [0, 0.22] })) }]} />
        <Svg width={size} height={size} style={StyleSheet.absoluteFill}>
          <Defs>
            {/* Clear in the middle, whiter toward the edge, like a glass bubble. */}
            <RadialGradient id={`orbShine${id}`} cx="50%" cy="50%" r="50%">
              <Stop offset="0" stopColor="#ffffff" stopOpacity="0" />
              <Stop offset="0.6" stopColor="#ffffff" stopOpacity="0.08" />
              <Stop offset="1" stopColor="#ffffff" stopOpacity="0.25" />
            </RadialGradient>
          </Defs>
          <Circle cx={size / 2} cy={size / 2} r={size / 2 - 1} fill={`url(#orbShine${id})`} stroke="#ffffff" strokeOpacity={hovered ? 0.6 : 0.3} strokeWidth={1} />
          {bars.map((b, i) => {
            const bh = b * size * 0.32
            return <Rect key={i} x={size / 2 - 21 + i * 12} y={size / 2 - bh / 2} width={4} height={bh} rx={2} fill="#ffffff" fillOpacity={0.8} />
          })}
        </Svg>
      </Animated.View>
    </Pressable>
  )
}

const s = StyleSheet.create({
  orb: { overflow: 'hidden', zIndex: 0 },
  webBlur: { backdropFilter: 'blur(6px)' } as ViewStyle,
  webFrost: { backdropFilter: 'blur(16px) saturate(160%)' } as ViewStyle,
  noRing: { outlineStyle: 'none' } as unknown as ViewStyle, // no browser focus box around the circle
})
