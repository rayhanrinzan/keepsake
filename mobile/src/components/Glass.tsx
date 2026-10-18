import { BlurView } from 'expo-blur'
import { LinearGradient } from 'expo-linear-gradient'
import { useState } from 'react'
import type { ReactNode } from 'react'
import { Platform, StyleSheet, View } from 'react-native'
import type { StyleProp, ViewStyle } from 'react-native'
import Svg, { Defs, RadialGradient, Rect, Stop, LinearGradient as SvgGradient } from 'react-native-svg'
import { C } from '../lib/theme'

// Decoration sits behind the content (icons included) inside the glass's own stacking context.
const BEHIND = { zIndex: -1 }

/**
 * Glass the way Apple draws it: almost clear over a strong blur, a sheen from above, a darker band
 * along the bottom for depth, and a hairline rim that only catches light at the top left and
 * bottom right instead of an even border.
 */
export function Glass({ radius = 999, style, children, strong = false, dark = false }: {
  radius?: number
  style?: StyleProp<ViewStyle>
  children?: ReactNode
  strong?: boolean
  dark?: boolean // glass on the black pull-up panel
}) {
  const [size, setSize] = useState({ w: 0, h: 0 })
  const r = Math.min(radius, size.h / 2 || radius)
  const edge = dark ? '#ffffff' : '#9aa6b1'
  const id = dark ? 'Dark' : 'Light'
  return (
    <View style={[{ borderRadius: r }, dark ? s.shadowDark : s.shadowLight]}>
      <View style={[{ borderRadius: r, overflow: 'hidden', zIndex: 0 }, style]} onLayout={e => setSize({ w: e.nativeEvent.layout.width, h: e.nativeEvent.layout.height })}>
        <BlurView intensity={dark ? 40 : 30} tint={dark ? 'dark' : 'light'} style={[StyleSheet.absoluteFill, BEHIND, Platform.OS === 'web' && s.webBlur]} />
        <View style={[StyleSheet.absoluteFill, BEHIND, { backgroundColor: dark ? 'rgba(255,255,255,0.055)' : strong ? C.glassStrong : C.glass }]} />
        {/* Sheen from above, so it reads as a curved surface. */}
        <LinearGradient colors={dark ? ['rgba(255,255,255,0.16)', 'rgba(255,255,255,0.03)', 'rgba(255,255,255,0)'] : ['rgba(255,255,255,0.95)', 'rgba(255,255,255,0.2)', 'rgba(255,255,255,0)']} locations={[0, 0.45, 0.7]} style={[StyleSheet.absoluteFill, BEHIND]} />
        {/* Depth along the bottom inside edge. */}
        <LinearGradient colors={dark ? ['rgba(0,0,0,0)', 'rgba(0,0,0,0.28)'] : ['rgba(120,135,150,0)', 'rgba(120,135,150,0.12)']} locations={[0.55, 1]} style={[StyleSheet.absoluteFill, BEHIND]} />
        {size.w > 0 && (
          <Svg width={size.w} height={size.h} style={[StyleSheet.absoluteFill, BEHIND]} pointerEvents="none">
            <Defs>
              <SvgGradient id={`spec${id}`} x1="0" y1="0" x2="0.3" y2="1">
                <Stop offset="0" stopColor={edge} stopOpacity={dark ? 0.6 : 1} />
                <Stop offset="0.45" stopColor={edge} stopOpacity={dark ? 0.08 : 0.3} />
                <Stop offset="1" stopColor={edge} stopOpacity={dark ? 0.22 : 0.55} />
              </SvgGradient>
              {/* Bright catch lights on the top left curve and, softer, the bottom right. */}
              <RadialGradient id={`catchA${id}`} cx="0.1" cy="0" rx="0.28" ry="0.9">
                <Stop offset="0" stopColor="#ffffff" stopOpacity="1" />
                <Stop offset="1" stopColor="#ffffff" stopOpacity="0" />
              </RadialGradient>
              <RadialGradient id={`catchB${id}`} cx="0.92" cy="1" rx="0.22" ry="0.8">
                <Stop offset="0" stopColor="#ffffff" stopOpacity={dark ? 0.6 : 0.8} />
                <Stop offset="1" stopColor="#ffffff" stopOpacity="0" />
              </RadialGradient>
              <SvgGradient id={`inner${id}`} x1="0" y1="0" x2="0" y2="1">
                <Stop offset="0" stopColor="#ffffff" stopOpacity={dark ? 0.3 : 0.9} />
                <Stop offset="0.5" stopColor="#ffffff" stopOpacity="0" />
              </SvgGradient>
            </Defs>
            {/* The thickness of the glass: a faint line just inside the top edge. */}
            <Rect x={1.5} y={1.5} width={size.w - 3} height={size.h - 3} rx={r - 1.5} ry={r - 1.5} fill="none" stroke={`url(#inner${id})`} strokeWidth={1} />
            {/* The hairline rim that catches the light. */}
            <Rect x={0.5} y={0.5} width={size.w - 1} height={size.h - 1} rx={r - 0.5} ry={r - 0.5} fill="none" stroke={`url(#spec${id})`} strokeWidth={1} />
            <Rect x={0.5} y={0.5} width={size.w - 1} height={size.h - 1} rx={r - 0.5} ry={r - 0.5} fill="none" stroke={`url(#catchA${id})`} strokeWidth={1.25} />
            <Rect x={0.5} y={0.5} width={size.w - 1} height={size.h - 1} rx={r - 0.5} ry={r - 0.5} fill="none" stroke={`url(#catchB${id})`} strokeWidth={1} />
          </Svg>
        )}
        {children}
      </View>
    </View>
  )
}

const s = StyleSheet.create({
  shadowDark: { shadowColor: '#000', shadowOpacity: 0.4, shadowRadius: 22, shadowOffset: { width: 0, height: 10 }, elevation: 8 },
  shadowLight: { shadowColor: '#1c2b36', shadowOpacity: 0.08, shadowRadius: 18, shadowOffset: { width: 0, height: 8 }, elevation: 3 },
  webBlur: { backdropFilter: 'blur(40px) saturate(180%)' } as ViewStyle,
})
