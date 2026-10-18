import * as Speech from 'expo-speech'
import { Platform } from 'react-native'
import { getVoice, tts } from './api'
import type { VoiceConfig } from './api'
import type { Settings } from './settings'

// ---- speaking: the Grok voice chosen on the Keepsake (played from the laptop's /api/tts, so the key
// stays there), or the phone/browser's own voice when Grok isn't set up or doesn't answer ----

const web = Platform.OS === 'web' && typeof window !== 'undefined' && typeof Audio !== 'undefined'
const DEFAULT_RATE = 0.85 // Settings' "How fast I talk" default; Grok plays at its own speed there

let config: VoiceConfig | null = null

/** The saved voice. Asked again until the Keepsake answers (it may still be starting up). */
async function currentConfig(): Promise<VoiceConfig | null> {
  if (!config) config = await getVoice().catch(() => null)
  return config
}

// Recent Grok audio by text + voice: repeated lines ("Are you looking for something?") play at once.
const cache = new Map<string, Blob>()

async function grokAudio(text: string, c: VoiceConfig): Promise<Blob> {
  const key = `${c.voice_id}|${c.speed}|${text}`
  const hit = cache.get(key)
  if (hit) return hit
  let blob: Blob
  try {
    blob = await tts(text)
  } catch (e) {
    if (e instanceof Error && e.message.endsWith(' 503')) throw e // no Grok key on the laptop
    await new Promise(r => setTimeout(r, 400)) // one retry: one slow request shouldn't change the voice
    blob = await tts(text)
  }
  cache.set(key, blob)
  if (cache.size > 40) cache.delete(cache.keys().next().value as string)
  return blob
}

let player: HTMLAudioElement | null = null
let endPlayback: (() => void) | null = null
let seq = 0 // bumps on every speak/stop, so a slow Grok reply can't talk over a newer one
let pending = false // waiting for Grok audio: counts as speaking

const getPlayer = () => (player ??= new Audio())

function playBlob(blob: Blob, s: Settings): Promise<void> {
  const audio = getPlayer()
  const url = URL.createObjectURL(blob)
  return new Promise<void>((resolve, reject) => {
    let done = false
    const finish = (err?: unknown) => {
      if (done) return
      done = true
      endPlayback = null
      URL.revokeObjectURL(url)
      err ? reject(err) : resolve()
    }
    endPlayback = () => finish()
    audio.onended = () => finish()
    audio.onerror = () => finish(new Error('Audio playback failed'))
    audio.src = url
    audio.volume = s.voiceVolume
    audio.playbackRate = s.voiceRate / DEFAULT_RATE
    audio.play().catch(finish) // e.g. blocked before the page was tapped
    setTimeout(() => finish(), 60_000) // never hang the conversation
  })
}

function speakBuiltIn(text: string, s: Settings, onDone?: () => void) {
  Speech.speak(text, { rate: s.voiceRate, volume: s.voiceVolume, onDone, onStopped: onDone })
}

function stopAudio() {
  player?.pause()
  endPlayback?.()
  Speech.stop()
}

/** Say `text`, then call `onDone`. Uses the Grok voice when the Keepsake has it on. */
export function speak(text: string, s: Settings, onDone?: () => void) {
  const mine = ++seq
  stopAudio()
  pending = web
  ;(async () => {
    const c = web ? await currentConfig() : null
    if (mine !== seq) return
    if (c?.provider === 'grok') {
      try {
        const blob = await grokAudio(text, c)
        if (mine !== seq) return // stopped or replaced while Grok was generating
        pending = false
        await playBlob(blob, s)
        if (mine === seq) onDone?.()
        return
      } catch (e) {
        if (mine !== seq) return
        console.warn('Grok voice unavailable, using the built-in voice:', e)
      }
    }
    pending = false
    speakBuiltIn(text, s, onDone)
  })()
}

export function stopSpeaking() {
  seq++
  pending = false
  stopAudio()
}

export async function stillSpeaking(): Promise<boolean> {
  if (pending || (player && !player.paused && !player.ended)) return true
  return Speech.isSpeakingAsync()
}

let unlocked = false

/** 0.1 s of silence, played from a tap so the browser lets the page speak on its own later. */
function silentWav(): string {
  const n = 800
  const v = new DataView(new ArrayBuffer(44 + n))
  const tag = (o: number, t: string) => [...t].forEach((ch, i) => v.setUint8(o + i, ch.charCodeAt(0)))
  tag(0, 'RIFF'); v.setUint32(4, 36 + n, true); tag(8, 'WAVE'); tag(12, 'fmt ')
  v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true)
  v.setUint32(24, 8000, true); v.setUint32(28, 8000, true); v.setUint16(32, 1, true); v.setUint16(34, 8, true)
  tag(36, 'data'); v.setUint32(40, n, true)
  for (let i = 0; i < n; i++) v.setUint8(44 + i, 128)
  return URL.createObjectURL(new Blob([v.buffer], { type: 'audio/wav' }))
}

/** Browsers mute audio a page starts by itself until it has played once from a tap or key press.
 *  Call this from such an event; prompts like "Are you looking for something?" are audible after. */
export function unlockSpeech() {
  if (unlocked || !web) return
  unlocked = true
  const u = new SpeechSynthesisUtterance(' ')
  u.volume = 0
  window.speechSynthesis?.speak(u)
  const audio = getPlayer()
  audio.src = silentWav()
  audio.play().catch(() => undefined)
}

// ---- listening ----

type Rec = {
  start: () => void; stop: () => void; abort: () => void
  onresult: ((e: any) => void) | null; onend: (() => void) | null; onerror: ((e: any) => void) | null
  interimResults: boolean; continuous: boolean; lang: string; maxAlternatives: number
}

const Recognition = (): (new () => Rec) | undefined => {
  if (Platform.OS !== 'web' || typeof window === 'undefined') return undefined
  const w = window as any
  return w.SpeechRecognition || w.webkitSpeechRecognition
}

/**
 * Speech to text. The browser has it built in; on a phone it needs a development build with
 * expo-speech-recognition (Expo Go can't do it), so for now the phone falls back to typing.
 */
export function canListen() {
  return Boolean(Recognition())
}

export function listen(onText: (text: string, final: boolean) => void, onEnd: () => void) {
  pauseWake() // only one recognizer can hold the mic
  const R = Recognition()!
  const rec = new R()
  rec.lang = 'en-US'
  rec.interimResults = true
  rec.onresult = e => {
    const r = e.results[e.results.length - 1]
    onText(r[0].transcript, r.isFinal)
  }
  rec.onend = onEnd
  rec.onerror = onEnd
  rec.start()
  return () => rec.stop()
}

// ---- hands-free: listen in the background for "where is my …" and start a lookup, like a smart speaker ----

export type WakeState = 'off' | 'listening' | 'paused' | 'blocked' | 'unsupported'

/** Phrases that start a lookup: "where are my keys", "have you seen my wallet", "hey Keepsake"… */
const WAKE_RE = /\b(?:where(?:'s|'re|'d| is| are| did i put| did i leave| did i)?\s+(?:my|the)|have you seen (?:my|the)|(?:help me |can you |could you )?find (?:my|the)|i (?:can'?t|cannot|couldn'?t) find|i lost (?:my|the)|i'?m looking for|hey,? keep ?sake)\b/i

/** The part of `text` from the wake phrase on, or null if there's no wake phrase. */
export function wakeMatch(text: string): string | null {
  const m = WAKE_RE.exec(text)
  return m ? text.slice(m.index).trim() : null
}

let wakeHandler: ((said: string) => void) | null = null
let wakeStateCb: ((s: WakeState) => void) | null = null
let wakeRec: Rec | null = null
let wakePaused = false
let wakeTimer: ReturnType<typeof setTimeout> | undefined

const setWakeState = (s: WakeState) => wakeStateCb?.(s)

function scheduleWake(delay: number) {
  clearTimeout(wakeTimer)
  wakeTimer = setTimeout(openWake, delay)
}

function openWake() {
  const R = Recognition()
  if (!R || !wakeHandler || wakePaused || wakeRec) return
  const rec = new R()
  wakeRec = rec
  rec.lang = 'en-US'
  rec.continuous = true
  rec.interimResults = false
  rec.maxAlternatives = 1
  let blocked = false
  rec.onresult = e => {
    if (wakeRec !== rec) return
    for (let i = e.resultIndex; i < e.results.length; i++) {
      if (!e.results[i].isFinal) continue
      const said = wakeMatch(e.results[i][0].transcript)
      if (said && wakeHandler) {
        const handler = wakeHandler
        pauseWake() // the conversation takes the mic; it resumes us when it's done
        handler(said)
        return
      }
    }
  }
  rec.onerror = e => {
    if (e?.error === 'not-allowed' || e?.error === 'service-not-allowed') blocked = true
  }
  rec.onend = () => {
    if (wakeRec === rec) wakeRec = null
    if (blocked) {
      wakeHandler = null
      setWakeState('blocked')
      return
    }
    // Browsers end continuous listening after a silence or a minute; just start again.
    if (wakeHandler && !wakePaused && !wakeRec) scheduleWake(400)
  }
  try {
    rec.start()
    setWakeState('listening')
  } catch {
    wakeRec = null
    scheduleWake(1000)
  }
}

/** Start listening in the background. `onWake` gets the utterance from the wake phrase on. */
export function startWakeListener(onWake: (said: string) => void, onState?: (s: WakeState) => void) {
  wakeStateCb = onState ?? null
  if (!Recognition()) return setWakeState('unsupported')
  wakeHandler = onWake
  wakePaused = false
  scheduleWake(0)
}

export function stopWakeListener() {
  wakeHandler = null
  clearTimeout(wakeTimer)
  const rec = wakeRec
  wakeRec = null
  try { rec?.abort() } catch { /* already stopped */ }
  setWakeState('off')
  wakeStateCb = null
}

/** Release the mic while Keepsake is talking or asking (so it doesn't hear itself). */
export function pauseWake() {
  wakePaused = true
  clearTimeout(wakeTimer)
  const rec = wakeRec
  wakeRec = null
  try { rec?.abort() } catch { /* already stopped */ }
  if (wakeHandler) setWakeState('paused')
}

export function resumeWake() {
  if (!wakeHandler) return
  wakePaused = false
  scheduleWake(300)
}
