import { router } from 'expo-router'
import { LinearGradient } from 'expo-linear-gradient'
import { ChevronLeft } from 'lucide-react-native'
import type { ReactNode } from 'react'
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native'
import type { StyleProp, TextProps, TextStyle, ViewStyle } from 'react-native'
import { useSafeAreaInsets } from 'react-native-safe-area-context'
import { useSettings } from '../lib/settings'
import { C, F, glow } from '../lib/theme'
import { Glass } from './Glass'
import { Sky } from './Sky'

/** Text that follows the person's text-size setting. */
export function T({ size = 18, weight = 'regular', color = C.ink, style, ...rest }: TextProps & {
  size?: number
  weight?: keyof typeof F
  color?: string
}) {
  const { s } = useSettings()
  const px = Math.round(size * s.textScale)
  return <Text {...rest} style={[{ fontFamily: F[weight], fontSize: px, lineHeight: Math.round(px * 1.28), color }, style as StyleProp<TextStyle>]} />
}

/** A page on the calm sky, with a big back button and title. */
export function Screen({ title, children, back = true, scroll = true, footer }: { title?: string; children: ReactNode; back?: boolean; scroll?: boolean; footer?: ReactNode }) {
  const inset = useSafeAreaInsets()
  const body = <View style={{ gap: 16 }}>{children}</View>
  return (
    <View style={{ flex: 1 }}>
      <Sky />
      <View style={[st.page, { paddingTop: inset.top + 36 }]}>
        {back && (
          <Pressable onPress={() => (router.canGoBack() ? router.back() : router.replace('/'))} accessibilityRole="button" accessibilityLabel="Back to my things" style={({ pressed }) => [{ alignSelf: 'flex-start', marginBottom: 14 }, pressed && st.pressed]}>
            <Glass style={st.back}>
              <ChevronLeft size={24} color={C.ink} />
              <T size={17} weight="medium">My things</T>
            </Glass>
          </Pressable>
        )}
        {title && <T size={36} style={{ marginBottom: 14, letterSpacing: -0.5 }} accessibilityRole="header">{title}</T>}
        {scroll ? (
          <ScrollView style={{ marginHorizontal: -20 }} contentContainerStyle={{ paddingHorizontal: 20, paddingBottom: inset.bottom + (footer ? 140 : 32) }} showsVerticalScrollIndicator={false}>{body}</ScrollView>
        ) : (
          <View style={{ flex: 1, paddingBottom: inset.bottom + 16 }}>{children}</View>
        )}
      </View>
      {footer}
    </View>
  )
}

/** Orange gradient, for the odd warm accent. */
export function Glow({ style, children, colors = glow }: { style?: StyleProp<ViewStyle>; children?: ReactNode; colors?: readonly [string, string, ...string[]] }) {
  return (
    <View style={[{ overflow: 'hidden' }, style]}>
      <LinearGradient colors={colors} start={{ x: 0.1, y: 0 }} end={{ x: 0.9, y: 1 }} style={StyleSheet.absoluteFill} />
      {children}
    </View>
  )
}

export function Card({ children, style, onPress, label }: { children: ReactNode; style?: StyleProp<ViewStyle>; onPress?: () => void; label?: string }) {
  const inner = <Glass radius={32} style={[st.card, style]}>{children}</Glass>
  if (!onPress) return inner
  return (
    <Pressable onPress={onPress} accessibilityRole="button" accessibilityLabel={label} style={({ pressed }) => pressed && st.pressed}>
      {inner}
    </Pressable>
  )
}

export function Empty({ children }: { children: ReactNode }) {
  return (
    <Glass radius={32} style={st.empty}>
      <T size={18} color={C.muted} style={{ textAlign: 'center' }}>{children}</T>
    </Glass>
  )
}

export const st = StyleSheet.create({
  page: { flex: 1, paddingHorizontal: 20 },
  back: { flexDirection: 'row', alignItems: 'center', gap: 2, paddingLeft: 10, paddingRight: 18, height: 48 },
  card: { padding: 20 },
  pressed: { transform: [{ scale: 0.97 }], opacity: 0.92 },
  empty: { padding: 28 },
})
