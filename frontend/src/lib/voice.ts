// Browser speech helpers (Web Speech API). Recognition is started by the Voice button, or hands-free
// by the wake listener at the bottom of this file ("where are my keys", "hey Keepsake").

import { api } from './api'
import type { VoiceConfig } from './api'

/* eslint-disable @typescript-eslint/no-explicit-any */
const Recognition: any =
  typeof window !== 'undefined'
    ? (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition
    : undefined

export const speechInputSupported = Boolean(Recognition)
export const speechOutputSupported = typeof window !== 'undefined' && 'speechSynthesis' in window

export class VoiceError extends Error {
  code: 'no-speech' | 'not-allowed' | 'unsupported' | 'aborted' | 'other'
  constructor(code: VoiceError['code'], message: string) {
    super(message)
    this.code = code
  }
}

let active: any = null

/** Listen for one utterance. Resolves with the final transcript. */
export function listenOnce(onInterim?: (text: string) => void): Promise<string> {
  if (!Recognition) {
    return Promise.reject(new VoiceError('unsupported', "Voice input isn't available in this browser."))
  }
  pauseWake() // only one recognizer can hold the mic
  return new Promise((resolve, reject) => {
    const rec = new Recognition()
    active = rec
    rec.lang = 'en-US'
    rec.interimResults = true
    rec.maxAlternatives = 1
    let finalText = ''
    let failed: VoiceError | null = null
    rec.onresult = (e: any) => {
      const r = e.results[e.results.length - 1]
      if (r.isFinal) finalText = r[0].transcript
      else onInterim?.(r[0].transcript)
    }
    rec.onerror = (e: any) => {
      const code = e.error === 'no-speech' ? 'no-speech'
        : e.error === 'not-allowed' || e.error === 'service-not-allowed' ? 'not-allowed'
          : e.error === 'aborted' ? 'aborted' : 'other'
      failed = new VoiceError(code, code === 'not-allowed'
        ? 'Microphone access is blocked. Allow it in your browser settings, or type instead.'
        : code === 'no-speech' ? "I didn't hear anything." : `Voice input error: ${e.error}`)
    }
    rec.onend = () => {
      active = null
      if (failed) reject(failed)
      else if (finalText.trim()) resolve(finalText.trim())
      else reject(new VoiceError('no-speech', "I didn't hear anything."))
    }
    try {
      rec.start()
    } catch {
      active = null
      reject(new VoiceError('other', "Couldn't start the microphone."))
    }
  })
}

// ---- speaking: the Grok voice (via the backend, so the key stays server-side) or the browser's ----

let config: VoiceConfig = { provider: 'browser', voice_id: 'eve', speed: 1 }

/** Called when voice settings load or change. */
export function setVoiceConfig(c: VoiceConfig) {
  config = c
}

let player: HTMLAudioElement | null = null
let endPlayback: (() => void) | null = null
let speakSeq = 0 // bumps on every speak/stop so a slow Grok response can't talk over a newer one

function getPlayer() {
  player ??= new Audio()
  return player
}

function playBlob(blob: Blob): Promise<void> {
  const audio = getPlayer()
  const url = URL.createObjectURL(blob)
  return new Promise<void>((resolve, reject) => {
    let done = false
    const finish = (err?: unknown) => {
      if (done) return
      done = true
      endPlayback = null
      URL.revokeObjectURL(url)
      if (err) reject(err)
      else resolve()
    }
    endPlayback = () => finish()
    audio.onended = () => finish()
    audio.onerror = () => finish(new Error('Audio playback failed'))
    audio.src = url
    audio.play().catch(finish) // e.g. NotAllowedError before the page was clicked
    setTimeout(() => finish(), 60_000) // never hang the conversation
  })
}

function speakBrowser(text: string, speed: number): Promise<void> {
  if (!speechOutputSupported) return Promise.resolve()
  return new Promise((resolve) => {
    window.speechSynthesis.cancel()
    const u = new SpeechSynthesisUtterance(text)
    u.rate = 0.98 * speed
    let done = false
    const finish = () => {
      if (!done) {
        done = true
        resolve()
      }
    }
    u.onend = finish
    u.onerror = finish
    setTimeout(finish, 1500 + (text.length * 90) / speed)
    window.speechSynthesis.speak(u)
  })
}

function stopAudio() {
  if (player) player.pause()
  endPlayback?.()
  if (speechOutputSupported) window.speechSynthesis.cancel()
}

/**
 * Speak and resolve when finished. Uses the configured voice; if Grok fails, falls back to the
 * browser voice so a conversation never goes silent. `strict` (Settings preview) throws instead.
 */
export async function speak(text: string, opts: Partial<VoiceConfig> & { strict?: boolean } = {}): Promise<void> {
  const c = { ...config, ...opts }
  const seq = ++speakSeq
  stopAudio()
  if (c.provider === 'grok') {
    try {
      const blob = await api.tts(text, { voice_id: c.voice_id, speed: c.speed })
      if (seq !== speakSeq) return // stopped or replaced while Grok was generating
      await playBlob(blob)
      return
    } catch (e) {
      if (opts.strict) throw e
      if (seq !== speakSeq) return
      console.warn('Grok voice unavailable, using the browser voice:', e)
    }
  }
  if (seq === speakSeq) await speakBrowser(text, c.speed)
}

let unlocked = false

/** 0.1 s of silence, used to unlock the audio element from a click. */
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

/** Browsers (Safari especially) mute audio a page starts on its own until it has played once
 *  from a click or key press. Call this from such an event; later prompts are then audible. */
export function unlockSpeech(): boolean {
  if (unlocked) return true
  if (speechOutputSupported) {
    const u = new SpeechSynthesisUtterance(' ')
    u.volume = 0
    window.speechSynthesis.speak(u)
  }
  const audio = getPlayer()
  audio.src = silentWav()
  audio.play().catch(() => undefined)
  unlocked = true
  return true
}

export function stopVoice() {
  speakSeq++
  try {
    active?.abort()
  } catch {
    /* already stopped */
  }
  active = null
  stopAudio()
}

// ---- hands-free: listen in the background for "where is my …" and start a lookup ----

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
let wakeRec: any = null
let wakePaused = false
let wakeTimer: ReturnType<typeof setTimeout> | undefined

const setWakeState = (s: WakeState) => wakeStateCb?.(s)

function scheduleWake(delay: number) {
  clearTimeout(wakeTimer)
  wakeTimer = setTimeout(openWake, delay)
}

function openWake() {
  if (!wakeHandler || wakePaused || wakeRec || active) return
  const rec = new Recognition()
  wakeRec = rec
  rec.lang = 'en-US'
  rec.continuous = true
  rec.interimResults = false
  rec.maxAlternatives = 1
  let blocked = false
  rec.onresult = (e: any) => {
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
  rec.onerror = (e: any) => {
    if (e.error === 'not-allowed' || e.error === 'service-not-allowed') blocked = true
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
  if (!Recognition) {
    setWakeState('unsupported')
    return
  }
  wakeHandler = onWake
  wakePaused = false
  scheduleWake(0)
}

export function stopWakeListener() {
  wakeHandler = null
  clearTimeout(wakeTimer)
  const rec = wakeRec
  wakeRec = null
  try {
    rec?.abort()
  } catch {
    /* already stopped */
  }
  setWakeState('off')
  wakeStateCb = null
}

/** Release the mic while Keepsake is talking or asking (so it doesn't hear itself). */
export function pauseWake() {
  wakePaused = true
  clearTimeout(wakeTimer)
  const rec = wakeRec
  wakeRec = null
  try {
    rec?.abort()
  } catch {
    /* already stopped */
  }
  if (wakeHandler) setWakeState('paused')
}

export function resumeWake() {
  if (!wakeHandler) return
  wakePaused = false
  scheduleWake(300)
}
