import { Check, X } from 'lucide-react-native'
import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { Animated, PanResponder, Platform, Pressable, StyleSheet, useWindowDimensions, View } from 'react-native'
import { useSafeAreaInsets } from 'react-native-safe-area-context'
import { ASSIST, useSettings } from '../lib/settings'
import type { Assist } from '../lib/settings'
import { P } from '../lib/theme'
import { T } from './ui'

const native = Platform.OS !== 'web'
const PEACH = '#ffb27a'
const KNOB = 26

const NAMES: Record<Assist, string> = { less: 'Less help', normal: 'Normal', more: 'More help' }

/** A setting's title with a small ? in the corner that opens what it does. */
function Section({ title, about, children }: { title: string; about: string; children: ReactNode }) {
  const [open, setOpen] = useState(false)
  return (
    <View style={s.section}>
      <View style={s.sectionHead}>
        <T size={18} weight="medium" color={P.line}>{title}</T>
        <Pressable onPress={() => setOpen(o => !o)} accessibilityRole="button" accessibilityLabel={`What is ${title}?`} hitSlop={8}
          style={({ pressed }) => [s.what, (open || pressed) && s.whatOn]}>
          <T size={13} weight="medium" color={open ? '#000000' : P.line}>?</T>
        </Pressable>
      </View>
      {open && <T size={14} color={P.soft} style={{ marginTop: 8 }}>{about}</T>}
      <View style={{ marginTop: 18 }}>{children}</View>
    </View>
  )
}

/** Less help, Normal, More help on a line: drag the knob or tap a stop, and it settles on the nearest one. */
function HelpSlider({ value, onChange }: { value: Assist; onChange: (v: Assist) => void }) {
  const [w, setW] = useState(0)
  const [drag, setDrag] = useState<number | null>(null) // where the knob is while it's being dragged
  const width = useRef(0)
  const start = useRef(0)
  const i = ASSIST.indexOf(value)
  const stop = (x: number) => Math.max(0, Math.min(2, Math.round((x / width.current) * 2)))

  const pan = useRef(PanResponder.create({
    onStartShouldSetPanResponder: () => true,
    onMoveShouldSetPanResponder: () => true,
    onPanResponderGrant: e => { start.current = e.nativeEvent.locationX; setDrag(start.current) },
    onPanResponderMove: (_, g) => setDrag(Math.max(0, Math.min(width.current, start.current + g.dx))),
    onPanResponderRelease: (_, g) => { onChange(ASSIST[stop(start.current + g.dx)]); setDrag(null) },
    onPanResponderTerminate: () => setDrag(null),
  })).current

  const x = drag ?? (w * i) / 2
  return (
    <View accessibilityRole="adjustable" accessibilityLabel={`How much help: ${NAMES[value]}`}
      accessibilityActions={[{ name: 'increment' }, { name: 'decrement' }]}
      onAccessibilityAction={e => onChange(ASSIST[Math.max(0, Math.min(2, i + (e.nativeEvent.actionName === 'increment' ? 1 : -1)))])}>
      <View style={s.track} onLayout={e => { width.current = e.nativeEvent.layout.width; setW(e.nativeEvent.layout.width) }} {...pan.panHandlers}>
        <View style={s.line} />
        <View style={[s.fill, { width: x }]} />
        {ASSIST.map((k, n) => <View key={k} style={[s.tick, { left: (w * n) / 2 - 4 }, n <= i && drag == null && s.tickOn]} />)}
        <View style={[s.knob, { left: x - KNOB / 2 }]} pointerEvents="none" />
      </View>
      <View style={s.labels}>
        {ASSIST.map(k => (
          <Pressable key={k} onPress={() => onChange(k)} hitSlop={6}>
            <T size={14} weight={k === value ? 'medium' : 'regular'} color={k === value ? PEACH : P.soft}>{NAMES[k]}</T>
          </Pressable>
        ))}
      </View>
    </View>
  )
}

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

        <Section title="How much help" about="How often Keepsake checks in to ask if you're forgetting something. Less help never checks in, Normal checks in now and then, and More help checks in often.">
          <HelpSlider value={prefs.assist} onChange={assist => set({ assist })} />
        </Section>

        <Section title="Speak first" about="When you tap the microphone, Keepsake asks &quot;What are you looking for?&quot; before it listens. Turn this off and it just listens straight away.">
          <Pressable onPress={() => set({ speakFirst: !prefs.speakFirst })} accessibilityRole="checkbox" accessibilityState={{ checked: prefs.speakFirst }} accessibilityLabel="Keepsake speaks first"
            style={({ pressed }) => [s.check, pressed && s.pressed]}>
            <View style={[s.box, prefs.speakFirst && s.boxOn]}>
              {prefs.speakFirst && <Check size={16} color="#000000" strokeWidth={3} />}
            </View>
            <T size={16} color={P.line}>Keepsake speaks first</T>
          </Pressable>
        </Section>
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
  section: { marginTop: 28, padding: 18, borderWidth: 1, borderColor: 'rgba(255,255,255,0.18)', borderRadius: P.radius },
  sectionHead: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  what: { width: 24, height: 24, borderRadius: 12, borderWidth: 1, borderColor: 'rgba(255,255,255,0.6)', alignItems: 'center', justifyContent: 'center' },
  whatOn: { backgroundColor: P.line, borderColor: P.line },
  track: { height: KNOB + 8, justifyContent: 'center', marginHorizontal: KNOB / 2 },
  line: { position: 'absolute', left: 0, right: 0, height: 2, backgroundColor: 'rgba(255,255,255,0.25)' },
  fill: { position: 'absolute', left: 0, height: 2, backgroundColor: PEACH },
  tick: { position: 'absolute', width: 8, height: 8, borderRadius: 4, backgroundColor: 'rgba(255,255,255,0.45)' },
  tickOn: { backgroundColor: PEACH },
  knob: { position: 'absolute', width: KNOB, height: KNOB, borderRadius: KNOB / 2, backgroundColor: PEACH, borderWidth: 3, borderColor: '#0d0d0d' },
  labels: { flexDirection: 'row', justifyContent: 'space-between', marginTop: 10 },
  check: { flexDirection: 'row', alignItems: 'center', gap: 12, borderRadius: P.radius },
  box: { width: 24, height: 24, borderRadius: 4, borderWidth: 1.5, borderColor: 'rgba(255,255,255,0.6)', alignItems: 'center', justifyContent: 'center' },
  boxOn: { backgroundColor: PEACH, borderColor: PEACH },
})
