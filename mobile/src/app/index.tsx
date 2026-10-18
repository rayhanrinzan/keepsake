import { router } from 'expo-router'
import { BellRing, Keyboard, Mic, Volume2 } from 'lucide-react-native'
import { useEffect, useId, useRef, useState } from 'react'
import { Image, Linking, Pressable, ScrollView, StyleSheet, TextInput, useWindowDimensions, View } from 'react-native'
import { useSafeAreaInsets } from 'react-native-safe-area-context'
import Svg, { Circle, Defs, RadialGradient, Stop } from 'react-native-svg'
import { CenterType } from '../components/CenterType'
import { SettingsSidebar } from '../components/SettingsSidebar'
import { T } from '../components/ui'
import { Unfold } from '../components/Unfold'
import { VoiceRibbon } from '../components/VoiceRibbon'
import { getObjects, getProfile, SAMPLE, where } from '../lib/api'
import type { TrackedObject } from '../lib/api'
import { answer } from '../lib/assistant'
import { itemPhoto } from '../lib/items'
import { canMeasure, measure } from '../lib/level'
import { CHECK_IN, useSettings } from '../lib/settings'
import { F, P } from '../lib/theme'
import { canListen, listen, speak, stillSpeaking, stopSpeaking } from '../lib/voice'

type Mode = 'idle' | 'listening' | 'thinking' | 'speaking' | 'answered'
const PROMPT = 'Speak to me. What do you need?'
const INVITE = "Tell me what you're looking for."
const CHECK = "Are you forgetting something? Tap the microphone and tell me what you're looking for."
const INK = '#111111' // black text on the white items bar
const MUTED = '#6b6b6b'
let unfolded = false // the blueprint opens once each time the app starts

/**
 * Home: a black page with a ribbon of light-orange and white threads flowing across the middle; tap
 * it to talk. Their things are listed on the white bar underneath. On launch the
 * blueprint unfolds first.
 */
export default function Home() {
  const inset = useSafeAreaInsets()
  const id = useId().replace(/:/g, '')
  const { height: h } = useWindowDimensions()
  const [intro, setIntro] = useState(!unfolded)
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
  const [micOn, setMicOn] = useState(false)
  const [menu, setMenu] = useState(false)
  const now = useRef(mode) // the mode right now, for the check-in timer
  now.current = mode
  const on = useRef(false) // the microphone stays on, conversation after conversation, until they turn it off
  const turn = useRef(0) // bumped when the microphone is turned off, so an answer still on its way is dropped
  const voice = canListen()

  useEffect(() => {
    const load = () => getObjects().then(o => { setItems(o); setError(false) }).catch(() => setError(true))
    load()
    const t = setInterval(load, 5000)
    return () => { clearInterval(t); on.current = false; stop.current?.(); stopSpeaking() }
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

  // With more help, Keepsake checks in every so often while nobody is talking to it.
  useEffect(() => {
    const every = CHECK_IN[prefs.assist]
    if (every == null || intro) return
    const t = setInterval(() => {
      if (!on.current && (now.current === 'idle' || now.current === 'answered')) say(CHECK)
    }, every * 60000)
    return () => clearInterval(t)
  }, [prefs.assist, intro])

  // The red button: lets their caregiver know they need help.
  async function help() {
    const p = await getProfile().catch(() => null)
    const c = p?.caretaker
    if (!c?.phone) return say("I don't have your caregiver's details yet, so I can't reach them from here.")
    say(`Opening a message to ${c.name} so you can let them know you need help.`)
    Linking.openURL(`sms:${c.phone}?body=${encodeURIComponent('I need help. (Sent from Keepsake)')}`).catch(() => {})
  }

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
    // In case the browser never says it finished: check whether it's still talking, and only move on
    // (and turn the mic orange) once it has really stopped.
    const check = () => { if (!done) stillSpeaking().then(on => (on ? setTimeout(check, 250) : finish()), finish) }
    setTimeout(check, 1200)
  }

  async function reply(q: string) {
    setMode('thinking')
    const mine = turn.current
    const a = await answer(q)
    if (mine !== turn.current) return
    // With the microphone on, it goes straight back to listening after answering.
    say(a.text, () => (on.current ? hear() : setMode('answered')))
  }

  // Listen for one question. The browser stops listening after a quiet spell, so while the
  // microphone is on it just starts again.
  function hear() {
    if (!on.current) return setMode('idle')
    setHeard('')
    setMode('listening')
    let got = false
    stop.current = listen(
      (text, final) => {
        if (!on.current) return // a last result can still arrive after it was turned off
        setHeard(text)
        if (final && !got) { got = true; reply(text) }
      },
      () => {
        if (got) return
        if (on.current) setTimeout(() => on.current && hear(), 300)
        else setMode(m => (m === 'listening' ? 'idle' : m))
      },
    )
  }

  function mic(next: boolean) {
    on.current = next
    setMicOn(next)
  }

  function talk() {
    if (on.current) {
      // Turn the microphone off and stop whatever it was doing.
      mic(false)
      turn.current++
      stop.current?.()
      stopSpeaking()
      return setMode('idle')
    }
    stopSpeaking()
    stop.current?.()
    setHeard('')
    if (!voice) {
      // On a phone without speech to text yet, it asks out loud and they type the answer.
      setTyping(true)
      return say(PROMPT, () => setMode('idle'))
    }
    mic(true)
    // With less help it just listens; otherwise Keepsake asks first.
    if (prefs.assist === 'less') hear()
    else say(PROMPT, hear)
  }

  const top = Math.round(h * 0.5)
  const active = mode !== 'idle' && mode !== 'answered'
  const energy = mode === 'listening' ? level : mode === 'speaking' ? pulse : 0
  // The mic fills white while Keepsake talks and orange while it's their turn.
  const theirs = mode === 'listening'
  const ours = mode === 'speaking' || mode === 'thinking'
  const lit = micOn && (theirs || ours)
  const tone = theirs ? '#ffb27a' : '#ffffff' // the same peach as the ribbon's threads
  // The ring reaches further out with each beat of the voice; it starts just past the button's edge.
  const reach = 50 + 28 * Math.min(1, theirs ? level * 2.5 : ours ? pulse : 0)
  const gap = 37 / reach
  // What they're saying as they say it; otherwise the last thing Keepsake said stays up.
  const mine = (mode === 'listening' || mode === 'thinking') && heard !== ''
  const caption = mine ? heard : said // their own words show in orange, like the mic
  // The question stays up while it's being asked and until they start talking.
  const asking = (mode === 'speaking' || mode === 'listening') && said === PROMPT && heard === ''

  return (
    <View style={s.page}>
      <ScrollView contentContainerStyle={{ flexGrow: 1 }} showsVerticalScrollIndicator={false}>
        <View style={[s.top, { minHeight: top, paddingTop: inset.top + 16, paddingBottom: 20 }]}>
          <View style={s.head}>
            <Pressable onPress={() => setMenu(true)} accessibilityRole="button" accessibilityLabel="Settings" hitSlop={12}>
              <Image source={require('../../assets/inside-icon.png')} style={s.logo} resizeMode="contain" />
            </Pressable>
            {SAMPLE ? <T size={12} weight="round" color={P.soft}>Sample</T> : <View />}
          </View>

          {/* What's being said, small, at the top. Before anything happens it invites them to ask. */}
          <View style={s.said}>
            {mode === 'idle'
              ? <T size={14} weight="light" color={P.soft} style={{ textAlign: 'center' }}>{INVITE}</T>
              : asking
              ? <T size={14} weight="light" color={P.soft} style={{ textAlign: 'center' }}>{PROMPT}</T>
              : caption !== '' && <CenterType text={caption} size={14} weight="light" color={mine ? '#ffb27a' : P.line} />}
            {mode === 'thinking' && heard === '' && <T size={14} weight="round" color={P.soft}>Let me check…</T>}
            {typing && (
              <TextInput autoFocus value={typed} onChangeText={setTyped} placeholder="Type it here" placeholderTextColor={P.faint} returnKeyType="send" style={s.input}
                onSubmitEditing={() => { if (typed.trim()) reply(typed.trim()); setTyped(''); setTyping(false) }} />
            )}
          </View>
          <View style={s.center}>
            <VoiceRibbon active={active} listening={mode === 'listening'} energy={energy} onPress={talk} label={micOn ? 'Turn the microphone off' : 'Turn the microphone on'} />
          </View>

          {/* Off: a white outline. Keepsake's turn: a soft white gradient with a speaker, and a glowing white ring
              around it with a gap between. Their turn: the same in orange with the mic. The ring beats with
              the voice. Tap again to turn it off. */}
          {/* Three buttons on one line: type a question, talk (the main one), and get help. */}
          <View style={s.micRow}>
          <View style={s.side}>
            <Pressable onPress={() => setTyping(t => !t)} accessibilityRole="button" accessibilityLabel={typing ? 'Stop typing' : 'Type what you are looking for'}
              style={({ pressed, hovered }: { pressed: boolean; hovered?: boolean }) => [StyleSheet.absoluteFill, s.sideBtn, (pressed || hovered || typing) && s.sideOn]}>
              <Keyboard size={20} color="#ffffff" />
            </Pressable>
          </View>
          <View style={s.micWrap}>
            {lit && (
              <Svg width={RING} height={RING} style={s.ring} pointerEvents="none">
                <Defs>
                  <RadialGradient id={`ring${id}`} cx="50%" cy="50%" r="50%">
                    <Stop offset={gap} stopColor={tone} stopOpacity="0" />
                    <Stop offset={gap + 0.02} stopColor={tone} stopOpacity="0.28" />
                    <Stop offset={gap + (1 - gap) * 0.4} stopColor={tone} stopOpacity="0.12" />
                    <Stop offset={gap + (1 - gap) * 0.75} stopColor={tone} stopOpacity="0.035" />
                    <Stop offset="1" stopColor={tone} stopOpacity="0" />
                  </RadialGradient>
                  <RadialGradient id={`fill${id}`} cx="50%" cy="50%" r="50%">
                    <Stop offset="0" stopColor={tone} stopOpacity="0.95" />
                    <Stop offset="0.45" stopColor={tone} stopOpacity="0.55" />
                    <Stop offset="1" stopColor={tone} stopOpacity="0.08" />
                  </RadialGradient>
                </Defs>
                <Circle cx={RING / 2} cy={RING / 2} r={reach} fill={`url(#ring${id})`} />
                <Circle cx={RING / 2} cy={RING / 2} r={32} fill={`url(#fill${id})`} />
              </Svg>
            )}
            <Pressable onPress={talk} accessibilityRole="button" accessibilityLabel={micOn ? 'Turn the microphone off' : 'Turn the microphone on'}
              style={({ pressed, hovered }: { pressed: boolean; hovered?: boolean }) => [s.mic, (pressed || hovered) && s.micHover, lit && s.micLit]}>
              {ours ? <Volume2 size={26} color={lit ? INK : P.line} /> : <Mic size={26} color={P.line} />}
            </Pressable>
          </View>
          <View style={s.side}>
            <Pressable onPress={help} accessibilityRole="button" accessibilityLabel="Let my caregiver know I need help"
              style={({ pressed, hovered }: { pressed: boolean; hovered?: boolean }) => [StyleSheet.absoluteFill, s.sideBtn, s.help, (pressed || hovered) && s.helpOn]}>
              <BellRing size={20} color="#ff6b6b" />
            </Pressable>
          </View>
          </View>
        </View>

        <View style={[s.panel, { paddingBottom: inset.bottom + 32 }]}>
          <T size={24} weight="medium" color={INK} style={{ marginBottom: 24 }}>My Items</T>
          {error && <T size={17} color={MUTED}>I can't reach your Keepsake right now. I'll keep trying.</T>}
          {items && items.length === 0 && <T size={17} color={MUTED}>Nothing is being tracked yet.</T>}
          <View style={{ gap: 12 }}>
            {items?.map(o => (
              <Pressable key={o.object_id} onPress={() => router.push({ pathname: '/item/[id]', params: { id: o.object_id } })} accessibilityRole="button" accessibilityLabel={`${o.name}. ${where(o)}. Tap to find it.`}
                style={({ pressed, hovered }: { pressed: boolean; hovered?: boolean }) => [s.item, !o.seen && { opacity: 0.6 }, (pressed || hovered) && s.itemOn]}>
                <Image source={itemPhoto(o.icon)} style={s.photo} resizeMode="contain" />
                <View style={{ flex: 1 }}>
                  <T size={21} color={INK} numberOfLines={1}>{o.name}</T>
                  <T size={14} weight="round" color={MUTED} numberOfLines={1}>{where(o)}</T>
                </View>
              </Pressable>
            ))}
          </View>
        </View>
      </ScrollView>
      <SettingsSidebar open={menu} onClose={() => setMenu(false)} />
      {intro && <Unfold onDone={() => { unfolded = true; setIntro(false) }} />}
    </View>
  )
}

const RING = 180 // room for the glowing ring around the mic

const s = StyleSheet.create({
  page: { flex: 1, backgroundColor: '#000000' },
  top: { paddingHorizontal: 22 },
  head: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  logo: { width: 40, height: 22 },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', marginHorizontal: -22, minHeight: 200 },
  said: { minHeight: 44, alignItems: 'center', justifyContent: 'flex-start', gap: 8, paddingHorizontal: 12, marginTop: 36 },
  input: { width: 300, height: 44, paddingHorizontal: 16, fontSize: 16, fontFamily: F.round, color: P.line, borderWidth: 1, borderColor: P.faint, borderRadius: P.radius },
  mic: { width: 64, height: 64, borderRadius: 32, alignItems: 'center', justifyContent: 'center', borderWidth: 1.5, borderColor: '#ffffff' },
  micRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 28 },
  side: { width: 46, height: 46 },
  sideBtn: { borderRadius: 23, alignItems: 'center', justifyContent: 'center', borderWidth: 1.5, borderColor: '#ffffff' },
  sideOn: { backgroundColor: 'rgba(255,255,255,0.12)' },
  help: { borderColor: '#ff6b6b' },
  helpOn: { backgroundColor: 'rgba(255,107,107,0.15)' },
  micWrap: { width: 64, height: 64 },
  ring: { position: 'absolute', left: (64 - RING) / 2, top: (64 - RING) / 2 },
  micLit: { borderColor: '#ffffff', borderWidth: 1 },
  micHover: { borderColor: '#ffffff', backgroundColor: 'rgba(255,255,255,0.08)' },
  panel: { backgroundColor: P.sheet, borderTopLeftRadius: P.radius, borderTopRightRadius: P.radius, paddingHorizontal: 24, paddingTop: 32, flexGrow: 1 },
  item: { flexDirection: 'row', alignItems: 'center', gap: 24, paddingVertical: 16, paddingLeft: 24, paddingRight: 20, borderRadius: P.radius, borderWidth: 1, borderColor: '#dcdcdc', backgroundColor: P.sheet },
  itemOn: { borderColor: INK, backgroundColor: '#f5f5f5' },
  photo: { width: 64, height: 40 },
})
