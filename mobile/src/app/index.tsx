import { router } from 'expo-router'
import { useEffect, useRef, useState } from 'react'
import { Image, Pressable, ScrollView, StyleSheet, TextInput, useWindowDimensions, View } from 'react-native'
import { useSafeAreaInsets } from 'react-native-safe-area-context'
import { Aura } from '../components/Aura'
import { CenterType } from '../components/CenterType'
import { GlassPill } from '../components/GlassPill'
import { T } from '../components/ui'
import { VoiceOrb } from '../components/VoiceOrb'
import { getObjects, SAMPLE, where } from '../lib/api'
import type { TrackedObject } from '../lib/api'
import { answer } from '../lib/assistant'
import { itemPhoto } from '../lib/items'
import { canMeasure, measure } from '../lib/level'
import { useSettings } from '../lib/settings'
import { F, O } from '../lib/theme'
import { canListen, listen, speak, stopSpeaking } from '../lib/voice'

type Mode = 'idle' | 'listening' | 'thinking' | 'speaking' | 'answered'
const PROMPT = 'Speak to me. What do you need?'

/**
 * Home: one orange page. The glass voice circle floats in a warm aura with the voice line running
 * through it; tap it to talk. Their things sit underneath on a white sheet in grey ovals.
 */
export default function Home() {
  const inset = useSafeAreaInsets()
  const { height: h } = useWindowDimensions()
  const { s: prefs } = useSettings()
  const [items, setItems] = useState<TrackedObject[] | null>(null)
  const [error, setError] = useState(false)
  const [mode, setMode] = useState<Mode>('idle')
  const [heard, setHeard] = useState('')
  const [said, setSaid] = useState('')
  const [level, setLevel] = useState(0)
  const [pulse, setPulse] = useState(0)
  const [typing, setTyping] = useState(false)
  const [typed, setTyped] = useState('')
  const stop = useRef<(() => void) | null>(null)
  const voice = canListen()

  useEffect(() => {
    const load = () => getObjects().then(o => { setItems(o); setError(false) }).catch(() => setError(true))
    load()
    const t = setInterval(load, 5000)
    return () => { clearInterval(t); stop.current?.(); stopSpeaking() }
  }, [])

  // The voice line follows the microphone while it listens.
  useEffect(() => {
    if (mode !== 'listening' || !canMeasure()) return
    const end = measure(setLevel)
    return () => { end(); setLevel(0) }
  }, [mode])

  // While Keepsake is speaking, the line swells and settles like speech.
  useEffect(() => {
    if (mode !== 'speaking') return setPulse(0)
    const id = setInterval(() => setPulse(0.25 + Math.abs(Math.sin(Date.now() / 140)) * 0.45 * Math.random() + 0.1), 120)
    return () => clearInterval(id)
  }, [mode])

  function say(text: string, then?: () => void) {
    setSaid(text)
    setMode('speaking')
    let done = false
    const finish = () => {
      if (done) return
      done = true
      then ? then() : setMode('answered')
    }
    speak(text, prefs, finish)
    setTimeout(finish, 900 + text.length * 65) // in case the browser never says it finished
  }

  async function reply(q: string) {
    setMode('thinking')
    const a = await answer(q)
    say(a.text)
  }

  function talk() {
    if (mode === 'listening') return stop.current?.()
    stopSpeaking()
    stop.current?.()
    setHeard('')
    if (!voice) {
      // On a phone without speech to text yet, it asks out loud and they type the answer.
      setTyping(true)
      return say(PROMPT, () => setMode('idle'))
    }
    say(PROMPT, () => {
      setMode('listening')
      stop.current = listen(
        (text, final) => {
          setHeard(text)
          if (final) reply(text)
        },
        () => setMode(m => (m === 'listening' ? 'idle' : m)),
      )
    })
  }

  const top = Math.round(h * 0.5)
  const active = mode !== 'idle' && mode !== 'answered'
  const energy = mode === 'listening' ? level : mode === 'speaking' ? pulse : 0
  const caption = mode === 'listening' || mode === 'thinking' ? heard : said

  return (
    <View style={s.page}>
      <ScrollView contentContainerStyle={{ flexGrow: 1 }} showsVerticalScrollIndicator={false}>
        {/* Scrolls with the page, so the voice line never shows through the items panel. */}
        <Aura height={top + 60} center={top * 0.5 + inset.top / 2} energy={energy} />
        <View style={[s.top, { height: top, paddingTop: inset.top + 16 }]}>
          <View style={s.head}>
            {SAMPLE ? <T size={12} weight="round" color={O.soft}>Sample</T> : <View />}
            <Image source={require('../../assets/inside-icon.png')} style={s.logo} accessibilityLabel="Keepsake" resizeMode="contain" />
          </View>

          <View style={s.center}>
            <View style={s.above}>
              {active && (mode !== 'speaking' || said === PROMPT) && <T size={20} color={O.text} style={{ textAlign: 'center' }}>{PROMPT}</T>}
            </View>
            <VoiceOrb size={118} active={active} level={level} onPress={talk} label={mode === 'listening' ? 'Stop listening' : 'Talk to Keepsake'} />
            <View style={s.below}>
              {caption !== '' && caption !== PROMPT && <CenterType text={caption} size={20} color={O.text} />}
              {mode === 'thinking' && heard === '' && <T size={16} weight="round" color={O.soft}>Let me check…</T>}
              {typing && (
                <GlassPill style={s.inputWrap}>
                  <TextInput autoFocus value={typed} onChangeText={setTyped} placeholder="Type it here" placeholderTextColor={O.soft} returnKeyType="send" style={s.input}
                    onSubmitEditing={() => { if (typed.trim()) reply(typed.trim()); setTyped(''); setTyping(false) }} />
                </GlassPill>
              )}
            </View>
          </View>
        </View>

        <View style={[s.panel, { paddingBottom: inset.bottom + 32 }]}>
          <T size={24} weight="medium" color={O.ink} style={{ marginBottom: 28 }}>My Items</T>
          {error && <T size={17} color={O.inkSoft}>I can't reach your Keepsake right now. I'll keep trying.</T>}
          {items && items.length === 0 && <T size={17} color={O.inkSoft}>Nothing is being tracked yet.</T>}
          <View style={{ gap: 14 }}>
            {items?.map(o => (
              <Pressable key={o.object_id} onPress={() => router.push({ pathname: '/item/[id]', params: { id: o.object_id } })} accessibilityRole="button" accessibilityLabel={`${o.name}. ${where(o)}. Tap to find it.`}
                style={({ pressed }) => [s.item, !o.seen && { opacity: 0.6 }, pressed && { opacity: 0.7 }]}>
                <Image source={itemPhoto(o.icon)} style={s.photo} resizeMode="contain" />
                <View style={{ flex: 1 }}>
                  <T size={21} color={O.ink} numberOfLines={1}>{o.name}</T>
                  <T size={14} weight="round" color={O.inkSoft} numberOfLines={1}>{where(o)}</T>
                </View>
              </Pressable>
            ))}
          </View>
        </View>
      </ScrollView>
    </View>
  )
}

const s = StyleSheet.create({
  page: { flex: 1, backgroundColor: O.page },
  top: { paddingHorizontal: 22 },
  head: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  logo: { width: 40, height: 22 },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  above: { height: 56, justifyContent: 'flex-end', paddingBottom: 18 },
  below: { minHeight: 96, alignItems: 'center', gap: 12, paddingTop: 22, paddingHorizontal: 8 },
  inputWrap: { width: 300, height: 50, justifyContent: 'center' },
  input: { paddingHorizontal: 20, fontSize: 18, fontFamily: F.round, color: O.text, height: 50 },
  panel: { backgroundColor: O.sheet, borderTopLeftRadius: 28, borderTopRightRadius: 28, paddingHorizontal: 24, paddingTop: 32, flexGrow: 1 },
  item: { flexDirection: 'row', alignItems: 'center', gap: 24, paddingVertical: 18, paddingLeft: 32, paddingRight: 24, borderRadius: 999, backgroundColor: O.row },
  photo: { width: 64, height: 40 },
})
