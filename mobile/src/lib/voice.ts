import * as Speech from 'expo-speech'
import { Platform } from 'react-native'
import { getVoice, tts } from './api'
import type { VoiceConfig } from './api'
import type { Settings } from './settings'

const web = Platform.OS === 'web' && typeof window !== 'undefined'

// ---- speaking: the Grok voice (through the backend, so the key stays there) or the device's own ----
// Same behaviour as the web app: the voice settings live in the backend, a Grok failure falls back
// to the device voice so a conversation never goes silent, and repeated lines are cached. On a phone
// build (no audio player yet) it always uses the device voice.

let config: VoiceConfig = { provider: 'browser', voice_id: 'eve', speed: 1 }
let configLoaded = false

export function setVoiceConfig(c: VoiceConfig) {
  config = { provider: c.provider, voice_id: c.voice_id, speed: c.speed }
  configLoaded = true
}

async function currentConfig(): Promise<VoiceConfig> {
  if (!configLoaded) {
    try {
      setVoiceConfig(await getVoice())
    } catch {
      /* backend unreachable: use what we have */
    }
  }
  return config
}

const cache = new Map<string, Blob>()
async function grokAudio(text: string, voice: string, speed: number): Promise<Blob> {
  const key = `${voice}|${speed}|${text}`
  const hit = cache.get(key)
  if (hit) return hit
  let blob: Blob
  try {
    blob = await tts(text, voice, speed)
  } catch (e) {
    if ((e as { status?: number }).status === 503) throw e // no xAI key
    await new Promise(r => setTimeout(r, 400)) // one retry, so one slow request doesn't switch voices
    blob = await tts(text, voice, speed)
  }
  cache.set(key, blob)
  if (cache.size > 40) cache.delete(cache.keys().next().value as string)
  return blob
}

let player: HTMLAudioElement | null = null
let endPlayback: (() => void) | null = null
let seq = 0 // bumps on every speak/stop so a slow Grok reply can't talk over a newer line
let busy = false // from speak() until it finishes, including while Grok is still generating

function getPlayer() {
  player ??= new Audio()
  return player
}

function playBlob(blob: Blob, volume: number): Promise<void> {
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
    audio.volume = Math.max(0, Math.min(1, volume))
    audio.src = url
    audio.play().catch(finish)
    setTimeout(() => finish(), 60_000)
  })
}

function speakDevice(text: string, s: Settings, speed: number): Promise<void> {
  return new Promise(resolve => {
    Speech.stop()
    Speech.speak(text, { rate: s.voiceRate * speed, volume: s.voiceVolume, onDone: () => resolve(), onStopped: () => resolve(), onError: () => resolve() })
  })
}

function stopAudio() {
  if (player) player.pause()
  endPlayback?.()
  Speech.stop()
}

/** Say `text` in the chosen voice; `onDone` runs once it has finished (or was stopped). */
export function speak(text: string, s: Settings, onDone?: () => void) {
  say(text, s).finally(() => onDone?.())
}

/** Promise form of speak. `strict` (the voice preview) throws instead of falling back. */
export async function say(text: string, s: Settings, override?: Partial<VoiceConfig> & { strict?: boolean }): Promise<void> {
  const mine = ++seq
  stopAudio()
  busy = true
  try {
    const c = { ...(await currentConfig()), ...override }
    if (mine !== seq) return
    if (c.provider === 'grok' && web) {
      try {
        const blob = await grokAudio(text, c.voice_id, c.speed)
        if (mine !== seq) return
        await playBlob(blob, s.voiceVolume)
        return
      } catch (e) {
        if (override?.strict) throw e
        if (mine !== seq) return
        console.warn('Grok voice unavailable, using the device voice:', e)
      }
    }
    if (mine === seq) await speakDevice(text, s, c.speed)
  } finally {
    if (mine === seq) busy = false
  }
}

export function stopSpeaking() {
  seq++
  busy = false
  stopAudio()
}

export const stillSpeaking = async () => busy || (await Speech.isSpeakingAsync())

/** Browsers mute sound a page starts on its own until it has played once from a tap. The first tap
 *  anywhere plays a moment of silence, so later prompts ("Are you looking for something?") are heard. */
function silentWav(): string {
  const n = 800 // 0.1 s at 8 kHz
  const v = new DataView(new ArrayBuffer(44 + n))
  const tag = (o: number, t: string) => [...t].forEach((ch, i) => v.setUint8(o + i, ch.charCodeAt(0)))
  tag(0, 'RIFF'); v.setUint32(4, 36 + n, true); tag(8, 'WAVE'); tag(12, 'fmt ')
  v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true)
  v.setUint32(24, 8000, true); v.setUint32(28, 8000, true); v.setUint16(32, 1, true); v.setUint16(34, 8, true)
  tag(36, 'data'); v.setUint32(40, n, true)
  for (let i = 0; i < n; i++) v.setUint8(44 + i, 128)
  return URL.createObjectURL(new Blob([v.buffer], { type: 'audio/wav' }))
}

if (web) {
  const unlock = () => {
    const a = getPlayer()
    a.src = silentWav()
    a.play().catch(() => {})
    if ('speechSynthesis' in window) {
      const u = new SpeechSynthesisUtterance(' ')
      u.volume = 0
      window.speechSynthesis.speak(u)
    }
  }
  window.addEventListener('pointerdown', unlock, { once: true })
  window.addEventListener('keydown', unlock, { once: true })
}

// ---- listening ----

type Rec = { start: () => void; stop: () => void; abort: () => void; onresult: ((e: any) => void) | null; onend: (() => void) | null; onerror: ((e: any) => void) | null; interimResults: boolean; continuous: boolean; lang: string }
const Recognition: any = web ? (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition : undefined
let active: Rec | null = null

/**
 * Speech to text. The browser has it built in; on a phone it needs a development build with
 * expo-speech-recognition (Expo Go can't do it), so for now the phone falls back to typing.
 */
export function canListen() {
  return Boolean(Recognition)
}

export function listen(onText: (text: string, final: boolean) => void, onEnd: () => void) {
  pauseWake() // only one recognizer can hold the mic
  const rec: Rec = new Recognition()
  active = rec
  rec.lang = 'en-US'
  rec.interimResults = true
  rec.onresult = e => {
    const r = e.results[e.results.length - 1]
    onText(r[0].transcript, r.isFinal)
  }
  rec.onend = () => { if (active === rec) active = null; onEnd() }
  rec.onerror = () => {}
  rec.start()
  return () => rec.stop()
}

// ---- hands-free: listen in the background for "where is my …" and start a lookup (web app parity) ----

export type WakeState = 'off' | 'listening' | 'paused' | 'blocked' | 'unsupported'

/** Phrases that start a lookup: "where are my keys", "where did I put my water bottle", "hey Keepsake"… */
const WAKE_RE = /\b(?:where(?:'s|'re|'d| is| are| did i put| did i leave| did i)?\s+(?:my|the)|have you seen (?:my|the)|(?:help me |can you |could you )?find (?:my|the)|i (?:can'?t|cannot|couldn'?t) find|i lost (?:my|the)|i'?m looking for|hey,? keep ?sake)\b/i

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
  if (!wakeHandler || wakePaused || wakeRec || active) return
  const rec: Rec = new Recognition()
  wakeRec = rec
  rec.lang = 'en-US'
  rec.continuous = true
  rec.interimResults = false
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
  rec.onerror = e => { if (e.error === 'not-allowed' || e.error === 'service-not-allowed') blocked = true }
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

export function startWakeListener(onWake: (said: string) => void, onState?: (s: WakeState) => void) {
  wakeStateCb = onState ?? null
  if (!Recognition) return setWakeState('unsupported')
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

/** Release the mic while Keepsake is talking or asking, so it doesn't hear itself. */
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
