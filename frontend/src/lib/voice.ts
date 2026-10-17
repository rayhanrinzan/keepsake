// Browser speech helpers (Web Speech API). Recognition is started explicitly by the Voice button;
// a future wake-word listener can start the same conversation by calling listenOnce().

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
