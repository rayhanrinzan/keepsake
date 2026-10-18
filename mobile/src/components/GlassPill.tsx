import type { ReactNode } from 'react'
import { Pressable, StyleSheet, View } from 'react-native'
import type { StyleProp, ViewStyle } from 'react-native'
import Svg, { Defs, LinearGradient, Rect, Stop } from 'react-native-svg'
import { useId, useState } from 'react'
import { O } from '../lib/theme'

/**
 * A glass oval on the orange page: a faint light tint and a thin rim that's brightest along the
 * top, like light catching the edge.
 */
export function GlassPill({ onPress, label, style, children }: { onPress?: () => void; label?: string; style?: StyleProp<ViewStyle>; children: ReactNode }) {
  const id = useId().replace(/:/g, '')
  const [box, setBox] = useState({ w: 0, h: 0 })
  const body = (pressed: boolean) => (
    <View style={[s.pill, pressed && { opacity: 0.75 }, style]} onLayout={e => setBox({ w: e.nativeEvent.layout.width, h: e.nativeEvent.layout.height })}>
      {box.w > 0 && (
        <Svg width={box.w} height={box.h} style={[StyleSheet.absoluteFill, s.behind]} pointerEvents="none">
          <Defs>
            <LinearGradient id={`pillRim${id}`} x1="0" y1="0" x2="0.2" y2="1">
              <Stop offset="0" stopColor="#fff3e2" stopOpacity="0.85" />
              <Stop offset="0.55" stopColor="#fff3e2" stopOpacity="0.3" />
              <Stop offset="1" stopColor="#fff3e2" stopOpacity="0.55" />
            </LinearGradient>
          </Defs>
          <Rect x={0.5} y={0.5} width={box.w - 1} height={box.h - 1} rx={(box.h - 1) / 2} fill={O.glass} stroke={`url(#pillRim${id})`} strokeWidth={1} />
        </Svg>
      )}
      {children}
    </View>
  )
  if (!onPress) return body(false)
  return <Pressable onPress={onPress} accessibilityRole="button" accessibilityLabel={label}>{({ pressed }) => body(pressed)}</Pressable>
}

const s = StyleSheet.create({
  pill: { borderRadius: 999, zIndex: 0 },
  behind: { zIndex: -1 },
})
