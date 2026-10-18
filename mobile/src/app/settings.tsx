import { Lock, Minus, Plus } from 'lucide-react-native'
import { Pressable, StyleSheet, Switch, View } from 'react-native'
import { Card, Screen, T, st } from '../components/ui'
import { useSettings } from '../lib/settings'
import { C } from '../lib/theme'
import { speak } from '../lib/voice'

const clamp = (v: number, a: number, b: number) => Math.round(Math.min(b, Math.max(a, v)) * 100) / 100

function Stepper({ label, value, onChange, step, min, max, show }: {
  label: string
  value: number
  onChange: (v: number) => void
  step: number
  min: number
  max: number
  show: (v: number) => string
}) {
  return (
    <Card style={s.row}>
      <View style={{ flex: 1 }}>
        <T size={20} weight="semibold">{label}</T>
        <T size={17} color={C.muted}>{show(value)}</T>
      </View>
      <Pressable onPress={() => onChange(clamp(value - step, min, max))} accessibilityLabel={`${label} lower`} style={({ pressed }) => [s.btn, pressed && st.pressed]}><Minus size={26} color={C.ink} /></Pressable>
      <Pressable onPress={() => onChange(clamp(value + step, min, max))} accessibilityLabel={`${label} higher`} style={({ pressed }) => [s.btn, pressed && st.pressed]}><Plus size={26} color={C.ink} /></Pressable>
    </Card>
  )
}

export default function SettingsScreen() {
  const { s: v, set } = useSettings()
  const pct = (x: number) => `${Math.round(x * 100)}%`

  return (
    <Screen title="Settings">
      <Stepper label="My voice volume" value={v.voiceVolume} step={0.1} min={0.2} max={1} show={pct}
        onChange={x => { set({ voiceVolume: x }); speak('This loud', { ...v, voiceVolume: x }) }} />
      <Stepper label="How fast I talk" value={v.voiceRate} step={0.05} min={0.6} max={1.1} show={x => (x < 0.8 ? 'Slow' : x < 0.95 ? 'Relaxed' : 'Normal')}
        onChange={x => { set({ voiceRate: x }); speak('This fast', { ...v, voiceRate: x }) }} />
      <Stepper label="Text size" value={v.textScale} step={0.1} min={0.9} max={1.4} show={pct} onChange={x => set({ textScale: x })} />
      <Card style={s.row}>
        <View style={{ flex: 1 }}>
          <T size={20} weight="semibold">Keep listening after I answer</T>
          <T size={17} color={C.muted}>So you can ask again without tapping</T>
        </View>
        <Switch value={v.listenAfterSpeaking} onValueChange={x => set({ listenAfterSpeaking: x })} trackColor={{ true: C.orange, false: C.hairline }} />
      </Card>

      {/* Only the caretaker can change this, from their side. */}
      <Card style={[s.row, { backgroundColor: C.sunken, borderColor: C.sunken }]}>
        <Lock size={24} color={C.muted} />
        <View style={{ flex: 1 }}>
          <T size={20} weight="semibold" color={C.muted}>Support level</T>
          <T size={17} color={C.muted}>Your caretaker sets this</T>
        </View>
      </Card>
    </Screen>
  )
}

const s = StyleSheet.create({
  row: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  btn: { width: 52, height: 52, borderRadius: 26, backgroundColor: C.sunken, alignItems: 'center', justifyContent: 'center' },
})
