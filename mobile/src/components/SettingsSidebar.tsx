import { Minus, Play, Plus, X } from 'lucide-react-native'
import { useEffect, useRef, useState } from 'react'
import { ActivityIndicator, Alert, Animated, Platform, Pressable, ScrollView, StyleSheet, useWindowDimensions, View } from 'react-native'
import { useSafeAreaInsets } from 'react-native-safe-area-context'
import { clearMemory, getHealth, getVoice, setCapture, setVoice } from '../lib/api'
import type { Health, VoiceConfig, VoiceInfo } from '../lib/api'
import type { Assist } from '../lib/settings'
import { useSettings } from '../lib/settings'
import { cameraStatus } from '../lib/status'
import { P } from '../lib/theme'
import { canListen, say, setVoiceConfig, stopSpeaking, tapToListen } from '../lib/voice'
import type { WakeState } from '../lib/voice'
import { T } from './ui'

const native = Platform.OS !== 'web'
const ACCENT = '#ffb27a'
const PREVIEW = "Hi, I'm Keepsake. I last saw your keys a few minutes ago."

const LEVELS: { key: Assist; title: string; detail: string }[] = [
  { key: 'more', title: 'More help', detail: 'Keepsake speaks first, asking what you\'re looking for, and checks in often to ask if you\'re forgetting something.' },
  { key: 'some', title: 'Some help', detail: 'Keepsake speaks first, and checks in now and then.' },
  { key: 'less', title: 'Less help', detail: 'Keepsake just listens when you tap the microphone, and doesn\'t check in.' },
]

const WAKE_TEXT: Record<WakeState, string> = {
  off: 'Off. Tap the microphone to talk.',
  listening: 'Listening. Just say "Where are my keys?"',
  paused: 'On.',
  blocked: 'Needs the microphone. Allow it in the browser settings.',
  unsupported: 'Needs a browser with speech recognition (Chrome, Edge or Safari).',
}

function Toggle({ on, onPress, title, detail, label }: { on: boolean; onPress: () => void; title: string; detail?: string; label: string }) {
  return (
    <Pressable onPress={onPress} accessibilityRole="switch" accessibilityState={{ checked: on }} accessibilityLabel={label}
      style={({ pressed }) => [s.option, s.row, on && s.optionOn, pressed && s.pressed]}>
      <View style={{ flex: 1, gap: 4 }}>
        <T size={18} weight="medium" color={P.line}>{title}</T>
        {detail ? <T size={14} color={P.soft}>{detail}</T> : null}
      </View>
      <View style={[s.track, on && s.trackOn]}>
        <View style={[s.knob, on && s.knobOn]} />
      </View>
    </Pressable>
  )
}

const Heading = ({ children }: { children: string }) => (
  <T size={14} color={P.soft} style={{ marginTop: 32, marginBottom: 12 }}>{children}</T>
)

/** Settings, sliding in from the left when the logo is tapped. Everything the web app's Settings has:
 *  voice (Grok or device, which Grok voice, speed, preview), hands-free, privacy, and setup. */
export function SettingsSidebar({ open, onClose, wakeState = 'off' }: { open: boolean; onClose: () => void; wakeState?: WakeState }) {
  const { s: prefs, set } = useSettings()
  const inset = useSafeAreaInsets()
  const { width } = useWindowDimensions()
  const panel = Math.min(360, width * 0.88)
  const x = useRef(new Animated.Value(0)).current
  const [info, setInfo] = useState<VoiceInfo | null>(null)
  const [health, setHealth] = useState<Health | null>(null)
  const [offline, setOffline] = useState(false)
  const [previewing, setPreviewing] = useState(false)
  const [note, setNote] = useState<string | null>(null)

  useEffect(() => {
    Animated.timing(x, { toValue: open ? 1 : 0, duration: 260, useNativeDriver: native }).start()
    if (!open) return
    setNote(null)
    getVoice().then(setInfo).catch(() => setInfo(null))
    const poll = () => getHealth().then(h => { setHealth(h); setOffline(false) }).catch(() => setOffline(true))
    poll()
    const t = setInterval(poll, 2000)
    return () => { clearInterval(t); stopSpeaking() }
  }, [open])

  async function changeVoice(patch: Partial<VoiceConfig>) {
    if (!info) return
    const next = { provider: info.provider, voice_id: info.voice_id, speed: info.speed, ...patch }
    next.speed = Math.round(Math.min(1.5, Math.max(0.7, next.speed)) * 100) / 100
    setInfo({ ...info, ...next })
    setVoiceConfig(next)
    try {
      setInfo(await setVoice(next))
    } catch (e) {
      setNote(e instanceof Error ? e.message : "Couldn't save the voice.")
    }
  }

  async function preview() {
    if (!info) return
    setNote(null)
    setPreviewing(true)
    try {
      await say(PREVIEW, prefs, { provider: info.provider, voice_id: info.voice_id, speed: info.speed, strict: true })
    } catch {
      setNote("The Grok voice didn't answer. Check the xAI key and credits.")
    }
    setPreviewing(false)
  }

  async function toggleCapture() {
    if (!health) return
    const next = !health.capture_enabled
    setHealth({ ...health, capture_enabled: next })
    await setCapture(next).catch(() => setNote("Couldn't change photo saving."))
  }

  function clearAll() {
    const go = () => clearMemory().then(() => setNote('Cleared. Keepsake starts fresh.')).catch(() => setNote("Couldn't clear the memories."))
    const msg = 'Forget every item and delete all saved photos? This can\'t be undone.'
    if (native) Alert.alert('Clear all memories?', msg, [{ text: 'Cancel', style: 'cancel' }, { text: 'Clear', style: 'destructive', onPress: go }])
    else if (window.confirm(msg)) go()
  }

  const status = cameraStatus(health, offline)
  const grok = info?.provider === 'grok'
  const capture = health?.capture_enabled ?? true

  return (
    <View style={StyleSheet.absoluteFill} pointerEvents={open ? 'auto' : 'none'}>
      <Animated.View style={[StyleSheet.absoluteFill, s.dim, { opacity: x }]}>
        <Pressable style={StyleSheet.absoluteFill} onPress={onClose} accessibilityLabel="Close settings" />
      </Animated.View>
      <Animated.View style={[s.panel, { width: panel, transform: [{ translateX: x.interpolate({ inputRange: [0, 1], outputRange: [-panel, 0] }) }] }]}>
        <ScrollView contentContainerStyle={{ paddingTop: inset.top + 16, paddingBottom: inset.bottom + 32, paddingHorizontal: 22 }} showsVerticalScrollIndicator={false}>
          <View style={s.head}>
            <T size={24} weight="medium" color={P.line}>Settings</T>
            <Pressable onPress={onClose} accessibilityRole="button" accessibilityLabel="Close settings" style={({ pressed }) => [s.close, pressed && s.pressed]}>
              <X size={22} color={P.line} />
            </Pressable>
          </View>
          <View style={[s.row, { gap: 8, marginTop: 6 }]} accessibilityRole="text" accessibilityLabel={`Camera: ${status.label}`}>
            <View style={[s.dot8, { backgroundColor: status.color }]} />
            <T size={14} color={P.soft}>{status.label}</T>
          </View>
          {note && <T size={14} color={ACCENT} style={{ marginTop: 14 }}>{note}</T>}

          <Heading>How much help</Heading>
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

          <Heading>Voice</Heading>
          {!info ? (
            <View style={[s.row, { gap: 10 }]}>
              <ActivityIndicator color={P.soft} />
              <T size={14} color={P.soft}>{offline ? "Can't reach Keepsake." : 'Loading…'}</T>
            </View>
          ) : (
            <View style={{ gap: 14 }}>
              <View style={s.segment} accessibilityRole="radiogroup" accessibilityLabel="Voice engine">
                {([['grok', 'Grok voice'], ['browser', 'Device voice']] as const).map(([key, label]) => {
                  const on = info.provider === key
                  const off = key === 'grok' && !info.grok_available
                  return (
                    <Pressable key={key} disabled={off} onPress={() => changeVoice({ provider: key })} accessibilityRole="radio" accessibilityState={{ checked: on, disabled: off }}
                      style={[s.segBtn, on && s.segOn, off && { opacity: 0.4 }]}>
                      <T size={15} weight="medium" color={on ? '#111' : P.line}>{label}</T>
                    </Pressable>
                  )
                })}
              </View>
              {!info.grok_available && <T size={13} color={P.soft}>Grok voices need XAI_API_KEY in the backend's .env.</T>}
              {grok && native && <T size={13} color={P.soft}>On a phone build the device voice is used; Grok plays in the browser.</T>}
              {grok && (
                <View style={s.chips}>
                  {info.voices.map(v => {
                    const on = info.voice_id === v.voice_id
                    return (
                      <Pressable key={v.voice_id} onPress={() => changeVoice({ voice_id: v.voice_id })} accessibilityRole="radio" accessibilityState={{ checked: on }}
                        style={({ pressed }) => [s.chip, on && s.chipOn, pressed && s.pressed]}>
                        <T size={15} weight="medium" color={on ? '#111' : P.line}>{v.name}</T>
                      </Pressable>
                    )
                  })}
                </View>
              )}
              <View style={[s.row, { justifyContent: 'space-between' }]}>
                <T size={15} color={P.soft}>Speed</T>
                <View style={[s.row, { gap: 10 }]}>
                  <Pressable onPress={() => changeVoice({ speed: info.speed - 0.05 })} accessibilityRole="button" accessibilityLabel="Slower" style={({ pressed }) => [s.step, pressed && s.pressed]}>
                    <Minus size={18} color={P.line} />
                  </Pressable>
                  <T size={16} weight="medium" color={P.line} style={{ minWidth: 48, textAlign: 'center' }}>{info.speed.toFixed(2)}×</T>
                  <Pressable onPress={() => changeVoice({ speed: info.speed + 0.05 })} accessibilityRole="button" accessibilityLabel="Faster" style={({ pressed }) => [s.step, pressed && s.pressed]}>
                    <Plus size={18} color={P.line} />
                  </Pressable>
                </View>
              </View>
              <Pressable onPress={preview} disabled={previewing} accessibilityRole="button" accessibilityLabel="Preview the voice"
                style={({ pressed }) => [s.option, s.row, { gap: 10, justifyContent: 'center' }, pressed && s.pressed]}>
                {previewing ? <ActivityIndicator color={P.line} /> : <Play size={18} color={P.line} />}
                <T size={16} weight="medium" color={P.line}>Preview</T>
              </Pressable>
            </View>
          )}

          <Heading>Hands-free</Heading>
          <Toggle on={prefs.handsFree} onPress={() => set({ handsFree: !prefs.handsFree })} label="Hands-free listening"
            title="Listen for questions" detail={tapToListen ? 'iPhone browsers only listen right after a tap, so use the microphone button. Hands-free works in Chrome on a computer or an Android phone.'
              : canListen() ? (prefs.handsFree ? WAKE_TEXT[wakeState] : WAKE_TEXT.off) : WAKE_TEXT.unsupported} />

          <Heading>Privacy</Heading>
          <T size={14} color={P.soft} style={{ marginBottom: 12 }}>
            Video is processed on the Keepsake computer. It saves selected item photos, not a recording.
          </T>
          <Toggle on={capture} onPress={toggleCapture} label="Save item photos" title="Save item photos"
            detail={capture ? undefined : 'Photo saving is paused. Last seen times still update.'} />
          <Pressable onPress={clearAll} accessibilityRole="button" style={({ pressed }) => [s.danger, pressed && s.pressed]}>
            <T size={16} weight="medium" color="#ff6b6b">Clear all memories and photos</T>
          </Pressable>

          {/* For whoever sets Keepsake up: turn the camera on to aim the mount, off before handing it over. */}
          <Heading>Setup</Heading>
          <Toggle on={prefs.showCamera} onPress={() => set({ showCamera: !prefs.showCamera })} label="Show camera feed on the home screen"
            title="Show camera feed" detail="What the worn camera sees, above My Items. For setting up; turn it off afterwards." />
        </ScrollView>
      </Animated.View>
    </View>
  )
}

const s = StyleSheet.create({
  dim: { backgroundColor: 'rgba(0,0,0,0.55)' },
  panel: { position: 'absolute', left: 0, top: 0, bottom: 0, backgroundColor: '#0d0d0d', borderRightWidth: 1, borderRightColor: 'rgba(255,255,255,0.12)' },
  head: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  close: { width: 40, height: 40, alignItems: 'center', justifyContent: 'center', borderRadius: P.radius },
  pressed: { backgroundColor: 'rgba(255,255,255,0.1)' },
  option: { flexDirection: 'row', gap: 14, padding: 16, borderWidth: 1, borderColor: 'rgba(255,255,255,0.18)', borderRadius: P.radius },
  optionOn: { borderColor: ACCENT, backgroundColor: 'rgba(255,178,122,0.08)' },
  dot: { width: 18, height: 18, marginTop: 3, borderRadius: 9, borderWidth: 1.5, borderColor: 'rgba(255,255,255,0.5)' },
  dotOn: { borderColor: ACCENT, backgroundColor: ACCENT },
  dot8: { width: 8, height: 8, borderRadius: 4 },
  row: { flexDirection: 'row', alignItems: 'center' },
  track: { width: 46, height: 28, borderRadius: 14, padding: 3, backgroundColor: 'rgba(255,255,255,0.18)' },
  trackOn: { backgroundColor: ACCENT },
  knob: { width: 22, height: 22, borderRadius: 11, backgroundColor: '#fff' },
  knobOn: { transform: [{ translateX: 18 }] },
  segment: { flexDirection: 'row', padding: 4, gap: 4, borderRadius: P.radius + 4, backgroundColor: 'rgba(255,255,255,0.08)' },
  segBtn: { flex: 1, height: 40, alignItems: 'center', justifyContent: 'center', borderRadius: P.radius },
  segOn: { backgroundColor: ACCENT },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  chip: { height: 40, paddingHorizontal: 16, alignItems: 'center', justifyContent: 'center', borderWidth: 1, borderColor: 'rgba(255,255,255,0.18)', borderRadius: P.radius },
  chipOn: { backgroundColor: ACCENT, borderColor: ACCENT },
  step: { width: 40, height: 40, alignItems: 'center', justifyContent: 'center', borderWidth: 1, borderColor: 'rgba(255,255,255,0.18)', borderRadius: P.radius },
  danger: { marginTop: 10, paddingVertical: 12, paddingHorizontal: 4, borderRadius: P.radius },
})
