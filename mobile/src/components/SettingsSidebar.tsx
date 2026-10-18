import { X } from 'lucide-react-native'
import { useEffect, useRef } from 'react'
import { Animated, Platform, Pressable, StyleSheet, useWindowDimensions, View } from 'react-native'
import { useSafeAreaInsets } from 'react-native-safe-area-context'
import type { Assist } from '../lib/settings'
import { useSettings } from '../lib/settings'
import { P } from '../lib/theme'
import { T } from './ui'

const native = Platform.OS !== 'web'

const LEVELS: { key: Assist; title: string; detail: string }[] = [
  { key: 'more', title: 'More help', detail: 'Keepsake speaks first, asking what you\'re looking for, and checks in often to ask if you\'re forgetting something.' },
  { key: 'some', title: 'Some help', detail: 'Keepsake speaks first, and checks in now and then.' },
  { key: 'less', title: 'Less help', detail: 'Keepsake just listens when you tap the microphone, and doesn\'t check in.' },
]

/** Settings, sliding in from the left when the logo is tapped. */
export function SettingsSidebar({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { s: prefs, set } = useSettings()
  const inset = useSafeAreaInsets()
  const { width } = useWindowDimensions()
  const panel = Math.min(340, width * 0.86)
  const x = useRef(new Animated.Value(0)).current

  useEffect(() => {
    Animated.timing(x, { toValue: open ? 1 : 0, duration: 260, useNativeDriver: native }).start()
  }, [open])

  return (
    <View style={StyleSheet.absoluteFill} pointerEvents={open ? 'auto' : 'none'}>
      <Animated.View style={[StyleSheet.absoluteFill, s.dim, { opacity: x }]}>
        <Pressable style={StyleSheet.absoluteFill} onPress={onClose} accessibilityLabel="Close settings" />
      </Animated.View>
      <Animated.View style={[s.panel, { width: panel, paddingTop: inset.top + 16, paddingBottom: inset.bottom + 24, transform: [{ translateX: x.interpolate({ inputRange: [0, 1], outputRange: [-panel, 0] }) }] }]}>
        <View style={s.head}>
          <T size={24} weight="medium" color={P.line}>Settings</T>
          <Pressable onPress={onClose} accessibilityRole="button" accessibilityLabel="Close settings" style={({ pressed }) => [s.close, pressed && s.pressed]}>
            <X size={22} color={P.line} />
          </Pressable>
        </View>

        <T size={14} color={P.soft} style={{ marginTop: 28, marginBottom: 12 }}>How much help</T>
        <View style={{ gap: 10 }}>
          {LEVELS.map(l => {
            const on = prefs.assist === l.key
            return (
              <Pressable key={l.key} onPress={() => set({ assist: l.key })} accessibilityRole="radio" accessibilityState={{ checked: on }} accessibilityLabel={`${l.title}. ${l.detail}`}
                style={({ pressed }) => [s.option, on && s.optionOn, pressed && s.pressed]}>
                <View style={[s.dot, on && s.dotOn]} />
                <View style={{ flex: 1, gap: 4 }}>
                  <T size={18} weight="medium" color={P.line}>{l.title}</T>
                  <T size={14} color={P.soft}>{l.detail}</T>
                </View>
              </Pressable>
            )
          })}
        </View>

        <T size={14} color={P.soft} style={{ marginTop: 28, marginBottom: 12 }}>Hands-free</T>
        <Pressable onPress={() => set({ handsFree: !prefs.handsFree })} accessibilityRole="switch" accessibilityState={{ checked: prefs.handsFree }}
          accessibilityLabel="Listen for where is my. Say “where are my keys?” any time and Keepsake answers, no tapping."
          style={({ pressed }) => [s.option, prefs.handsFree && s.optionOn, pressed && s.pressed]}>
          <View style={[s.box, prefs.handsFree && s.dotOn]} />
          <View style={{ flex: 1, gap: 4 }}>
            <T size={18} weight="medium" color={P.line}>Listen for “where is my…”</T>
            <T size={14} color={P.soft}>Say “where are my keys?” any time and Keepsake answers, no tapping.</T>
          </View>
        </Pressable>
      </Animated.View>
    </View>
  )
}

const s = StyleSheet.create({
  dim: { backgroundColor: 'rgba(0,0,0,0.55)' },
  panel: { position: 'absolute', left: 0, top: 0, bottom: 0, backgroundColor: '#0d0d0d', borderRightWidth: 1, borderRightColor: 'rgba(255,255,255,0.12)', paddingHorizontal: 22 },
  head: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  close: { width: 40, height: 40, alignItems: 'center', justifyContent: 'center', borderRadius: P.radius },
  pressed: { backgroundColor: 'rgba(255,255,255,0.1)' },
  option: { flexDirection: 'row', gap: 14, padding: 16, borderWidth: 1, borderColor: 'rgba(255,255,255,0.18)', borderRadius: P.radius },
  optionOn: { borderColor: '#ffb27a', backgroundColor: 'rgba(255,178,122,0.08)' },
  dot: { width: 18, height: 18, marginTop: 3, borderRadius: 9, borderWidth: 1.5, borderColor: 'rgba(255,255,255,0.5)' },
  box: { width: 18, height: 18, marginTop: 3, borderRadius: 4, borderWidth: 1.5, borderColor: 'rgba(255,255,255,0.5)' },
  dotOn: {borderColor: '#ffb27a', backgroundColor: '#ffb27a' },
})
