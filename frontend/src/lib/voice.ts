// Browser speech helpers (Web Speech API). Recognition is started explicitly by the Voice button;
// a future wake-word listener can start the same conversation by calling listenOnce().

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

/** Speak and resolve when finished (or after a safety timeout if the browser never reports the end). */
export function speak(text: string): Promise<void> {
  if (!speechOutputSupported) return Promise.resolve()
  return new Promise((resolve) => {
    window.speechSynthesis.cancel()
    const u = new SpeechSynthesisUtterance(text)
    u.rate = 0.98
    let done = false
    const finish = () => {
      if (!done) {
        done = true
        resolve()
      }
    }
    u.onend = finish
    u.onerror = finish
    setTimeout(finish, 1500 + text.length * 90)
    window.speechSynthesis.speak(u)
  })
}

let unlocked = false

/** Browsers (Safari especially) mute speech a page starts on its own until it has spoken once
 *  from a click or key press. Call this from such an event; later prompts are then audible. */
export function unlockSpeech(): boolean {
  if (unlocked || !speechOutputSupported) return unlocked
  const u = new SpeechSynthesisUtterance(' ')
  u.volume = 0
  window.speechSynthesis.speak(u)
  unlocked = true
  return true
}

export function stopVoice() {
  try {
    active?.abort()
  } catch {
    /* already stopped */
  }
  active = null
  if (speechOutputSupported) window.speechSynthesis.cancel()
}
