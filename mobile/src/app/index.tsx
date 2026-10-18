import { router } from 'expo-router'
import { BellRing, Keyboard, Mic, Volume2 } from 'lucide-react-native'
import { useEffect, useId, useRef, useState } from 'react'
import { Image, Linking, Platform, Pressable, ScrollView, StyleSheet, TextInput, useWindowDimensions, View } from 'react-native'
import { useSafeAreaInsets } from 'react-native-safe-area-context'
import Svg, { Circle, Defs, RadialGradient, Stop } from 'react-native-svg'
import { CenterType } from '../components/CenterType'
import { LiveCamera } from '../components/LiveCamera'
import { Thumb } from '../components/Photo'
import { SettingsSidebar } from '../components/SettingsSidebar'
import { T } from '../components/ui'
import { Unfold } from '../components/Unfold'
import { VoiceRibbon } from '../components/VoiceRibbon'
import { clockTime, EVENT_LABEL, getEvents, getHealth, getObjects, getProfile, SAMPLE, where } from '../lib/api'
import type { ActivityEvent, Health, TrackedObject } from '../lib/api'
import { answer } from '../lib/assistant'
import { itemPhoto } from '../lib/items'
import { canMeasure, measure } from '../lib/level'
import { CHECK_IN, useSettings } from '../lib/settings'
import { F, P } from '../lib/theme'
import { cameraStatus } from '../lib/status'
import { canListen, listen, pauseWake, resumeWake, speak, startWakeListener, stillSpeaking, stopSpeaking, stopWakeListener } from '../lib/voice'
import type { WakeState } from '../lib/voice'

type Mode = 'idle' | 'listening' | 'thinking' | 'speaking' | 'answered'
const PROMPT = 'Speak to me. What do you need?'
const INVITE = "Tell me what you're looking for."
const CHECK = "Are you forgetting something? Tap the microphone and tell me what you're looking for."
const INK = '#111111' // black text on the white items bar
const MUTED = '#6b6b6b'
let unfolded = false // the blueprint opens once each time the app starts
const POLL_MS = 1500 // like the web app
const LOST_ASK_MS = 10_000 // an item out of view this long gets "Are you looking for something?"
const LOOKING = 'Are you looking for something?'
const DECLINE = /^(no|nope|nah|nothing|i'?m (good|fine|ok(ay)?)|not really|no thanks?)\b/i
// A bare "yes" names no item, so Keepsake asks which one. "Yes, my keys" goes straight to the lookup.
const AFFIRM = /^(yes|yeah|yep|yup|ya|sure|i am|uh[- ]?huh|please|yes please|kind of|maybe)[.!]?$/i

function joinList(names: string[], last: 'and' | 'or') {
  return names.length < 2 ? names.join('') : `${names.slice(0, -1).join(', ')}, ${last} ${names[names.length - 1]}`
}

/** "Okay, which item?" plus the items Keepsake has seen (or, if none yet, everything it tracks). */
function whichItem(objects: TrackedObject[]) {
  const seen = objects.filter(o => o.seen).map(o => o.name.toLowerCase())
  if (seen.length) return `Okay, which item? I've seen your ${joinList(seen, 'and')}.`
  const all = objects.map(o => o.name.toLowerCase())
  return all.length ? `Okay, which item? I can look for your ${joinList(all, 'or')}.` : 'Okay, which item?'
}

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
  const [health, setHealth] = useState<Health | null>(null)
  const [events, setEvents] = useState<ActivityEvent[]>([])
  const [found, setFound] = useState<TrackedObject | null>(null) // the item the last answer was about
  const [wakeState, setWakeState] = useState<WakeState>('off')
  const [gestured, setGestured] = useState(Platform.OS !== 'web') // browsers need a tap before the mic
  const itemsRef = useRef<TrackedObject[]>([])
  const goneSince = useRef<Record<string, number>>({}) // item -> when it left the view (ms)
  const asked = useRef<Set<string>>(new Set()) // items already asked about since they left
  const latest = useRef({ converse: (_q: string) => {}, lookUp: (_s: string, _a: boolean) => {} }) // newest closures, for timers

  useEffect(() => {
    const load = async () => {
      try {
        const [o, h, e] = await Promise.all([getObjects(), getHealth().catch(() => null), getEvents(10).catch(() => [])])
        setItems(o)
        itemsRef.current = o
        setHealth(h)
        setEvents(e)
        setError(false)
        // An item seen in view this session that stays out of view LOST_ASK_MS: ask out loud, once.
        const t = Date.now()
        let due = false
        for (const item of o) {
          if (item.visible) {
            goneSince.current[item.object_id] = 0
            asked.current.delete(item.object_id)
          } else if (goneSince.current[item.object_id] === 0) {
            goneSince.current[item.object_id] = t
          } else if (goneSince.current[item.object_id] && t - goneSince.current[item.object_id] >= LOST_ASK_MS && !asked.current.has(item.object_id)) {
            asked.current.add(item.object_id)
            due = true
          }
        }
        if (due && !on.current && (now.current === 'idle' || now.current === 'answered')) latest.current.converse(LOOKING)
      } catch {
        setError(true)
      }
    }
    load()
    const t = setInterval(load, POLL_MS)
    return () => { clearInterval(t); on.current = false; stop.current?.(); stopSpeaking() }
  }, [])

  // Browsers only allow the microphone and sound after a tap or key press.
  useEffect(() => {
    if (gestured || typeof window === 'undefined') return
    const go = () => setGestured(true)
    window.addEventListener('pointerdown', go, { once: true })
    window.addEventListener('keydown', go, { once: true })
    return () => { window.removeEventListener('pointerdown', go); window.removeEventListener('keydown', go) }
  }, [gestured])

  // Hands-free, like the web app: "where are my keys" (or "where did I put my water bottle") starts a
  // lookup without touching anything.
  useEffect(() => {
    if (!prefs.handsFree || !voice || !gestured || intro) return
    startWakeListener(said => { if (!on.current) latest.current.lookUp(said, true) }, setWakeState)
    return () => stopWakeListener()
  }, [prefs.handsFree, voice, gestured, intro])

  // It steps aside while Keepsake talks or the microphone is on, so it doesn't hear itself.
  useEffect(() => {
    if (!prefs.handsFree) return
    if (!micOn && (mode === 'idle' || mode === 'answered')) resumeWake()
    else pauseWake()
  }, [mode, micOn, prefs.handsFree])

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
    setFound(a.object ?? null)
    // With the microphone on, it goes straight back to listening after answering.
    say(a.text, () => (on.current ? hear() : setMode('answered')))
  }

  /** Say something and wait until it's finished. */
  const sayAndWait = (text: string) => new Promise<void>(done => say(text, done))

  /** Listen for one reply (null if nothing was heard). */
  function hearOnce(): Promise<string | null> {
    return new Promise(done => {
      if (!voice) return done(null)
      setHeard('')
      setMode('listening')
      let got: string | null = null
      stop.current = listen((text, final) => { setHeard(text); if (final) got = text }, () => done(got))
    })
  }

  /** A short conversation Keepsake starts itself ("Are you looking for something?"), like the web app. */
  async function converse(question: string) {
    if (question === LOOKING && prefs.assist === 'less') return // less help never checks in (Amanda)
    const mine = ++turn.current
    setFound(null)
    await sayAndWait(question)
    if (mine !== turn.current || on.current) return
    let reply = await hearOnce()
    if (mine !== turn.current || on.current) return
    if (!reply) return setMode('idle')
    if (DECLINE.test(reply)) return say('Okay.')
    if (AFFIRM.test(reply.trim())) {
      await sayAndWait(whichItem(itemsRef.current))
      if (mine !== turn.current || on.current) return
      reply = await hearOnce()
      if (mine !== turn.current || on.current) return
      if (!reply) return setMode('idle')
      if (DECLINE.test(reply)) return say('Okay.')
    }
    reply_(reply, mine)
  }

  /** Started hands-free: `said` is what followed the wake phrase, e.g. "where are my keys". */
  async function lookUp(said: string, askIfUnknown: boolean) {
    const mine = ++turn.current
    stopSpeaking()
    setHeard(said)
    setMode('thinking')
    const a = await answer(said)
    if (mine !== turn.current) return
    if (askIfUnknown && !a.category) {
      // "Where is my…" with no item (or one we don't track): ask which item instead of apologising.
      await sayAndWait(whichItem(itemsRef.current))
      if (mine !== turn.current || on.current) return
      const reply = await hearOnce()
      if (mine !== turn.current || on.current) return
      if (!reply) return setMode('idle')
      if (DECLINE.test(reply)) return say('Okay.')
      return reply_(reply, mine)
    }
    setFound(a.object ?? null)
    say(a.text)
  }

  latest.current = { converse, lookUp }

  async function reply_(q: string, mine: number) {
    setMode('thinking')
    const a = await answer(q)
    if (mine !== turn.current) return
    setFound(a.object ?? null)
    say(a.text)
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
            {SAMPLE ? <T size={12} weight="round" color={P.soft}>Sample</T> : (
              <View style={s.status} accessibilityRole="text" accessibilityLabel={`Camera: ${cameraStatus(health, error).label}`}>
                <View style={[s.statusDot, { backgroundColor: cameraStatus(health, error).color }]} />
                <T size={12} weight="round" color={P.soft}>{cameraStatus(health, error).label}</T>
              </View>
            )}
          </View>

          {/* What's being said, small, at the top. Before anything happens it invites them to ask. */}
          <View style={s.said}>
            {mode === 'idle'
              ? <T size={14} weight="light" color={P.soft} style={{ textAlign: 'center' }}>
                  {prefs.handsFree && voice && !gestured ? 'Tap anywhere to turn on voice. Then just say "Where are my keys?"'
                    : prefs.handsFree && wakeState === 'listening' ? 'Just say "Where are my keys?"' : INVITE}
                </T>
              : asking
              ? <T size={14} weight="light" color={P.soft} style={{ textAlign: 'center' }}>{PROMPT}</T>
              : caption !== '' && <CenterType text={caption} size={14} weight="light" color={mine ? '#ffb27a' : P.line} />}
            {mode === 'thinking' && <T size={14} weight="round" color={P.soft}>Let me check…</T>}
            {found?.snapshot && mode !== 'thinking' && mode !== 'listening' && (
              <Pressable onPress={() => router.push({ pathname: '/item/[id]', params: { id: found.object_id } })} accessibilityRole="button"
                accessibilityLabel={`See the photo of your ${found.name.toLowerCase()}`} style={({ pressed }) => [s.found, pressed && s.sideOn]}>
                <Thumb snapshot={found.snapshot} width={56} height={42} alt="" />
                <T size={14} weight="medium" color={P.line}>See the photo</T>
              </Pressable>
            )}
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
          {prefs.showCamera && <LiveCamera />}
          <View style={{ marginBottom: 24, gap: 4 }}>
            {items && items.length > 0 && <T size={13} weight="round" color={MUTED}>{items.filter(o => o.seen).length} of {items.length} remembered</T>}
            <T size={24} weight="medium" color={INK}>My Items</T>
          </View>
          {error && <T size={17} color={MUTED}>I can't reach your Keepsake right now. I'll keep trying.</T>}
          {items && items.length === 0 && <T size={17} color={MUTED}>Nothing is being tracked yet.</T>}
          <View style={{ gap: 12 }}>
            {items?.map(o => (
              <Pressable key={o.object_id} onPress={() => router.push({ pathname: '/item/[id]', params: { id: o.object_id } })} accessibilityRole="button" accessibilityLabel={`${o.name}. ${where(o)}. Tap to find it.`}
                style={({ pressed, hovered }: { pressed: boolean; hovered?: boolean }) => [s.item, !o.seen && { opacity: 0.6 }, (pressed || hovered) && s.itemOn]}>
                <Image source={itemPhoto(o.icon)} style={s.photo} resizeMode="contain" />
                <View style={{ flex: 1 }}>
                  <T size={20} color={INK} numberOfLines={1}>{o.name}</T>
                  <T size={14} weight="round" color={MUTED} numberOfLines={2}>{where(o)}</T>
                </View>
                {o.snapshot && <Thumb snapshot={o.snapshot} width={60} height={45} alt={`Last photo of your ${o.name.toLowerCase()}`} />}
                {o.visible && <View style={s.live} accessibilityLabel="In view now" />}
              </Pressable>
            ))}
          </View>

          <T size={24} weight="medium" color={INK} style={{ marginTop: 40, marginBottom: 16 }}>Recent activity</T>
          {events.length === 0 && <T size={16} color={MUTED}>Nothing seen yet.</T>}
          {events.map(e => (
            <View key={e.id} style={s.event}>
              <T size={16} color={INK} numberOfLines={1} style={{ flex: 1 }}>
                {e.name} <T size={16} color={MUTED}>{(EVENT_LABEL[e.event_type] ?? e.event_type).toLowerCase()}</T>
              </T>
              <T size={13} weight="round" color={MUTED}>{clockTime(e.timestamp)}</T>
            </View>
          ))}
        </View>
      </ScrollView>
      <SettingsSidebar open={menu} onClose={() => setMenu(false)} wakeState={wakeState} />
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
  item: { flexDirection: 'row', alignItems: 'center', gap: 14, paddingVertical: 14, paddingLeft: 14, paddingRight: 14, borderRadius: P.radius, borderWidth: 1, borderColor: '#dcdcdc', backgroundColor: P.sheet },
  itemOn: { borderColor: INK, backgroundColor: '#f5f5f5' },
  photo: { width: 52, height: 36 },
  status: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  statusDot: { width: 7, height: 7, borderRadius: 4 },
  found: { flexDirection: 'row', alignItems: 'center', gap: 10, padding: 6, paddingRight: 14, borderWidth: 1, borderColor: P.faint, borderRadius: P.radius },
  live: { position: 'absolute', top: 10, right: 10, width: 8, height: 8, borderRadius: 4, backgroundColor: '#3ddc97' },
  event: { flexDirection: 'row', alignItems: 'baseline', gap: 12, paddingVertical: 10, borderBottomWidth: 1, borderBottomColor: '#eeeeee' },
})
