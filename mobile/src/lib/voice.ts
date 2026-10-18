import * as Speech from 'expo-speech'
import { Platform } from 'react-native'
import type { Settings } from './settings'

export function speak(text: string, s: Settings, onDone?: () => void) {
  Speech.stop()
  Speech.speak(text, { rate: s.voiceRate, volume: s.voiceVolume, onDone, onStopped: onDone })
}

export const stopSpeaking = () => Speech.stop()
export const stillSpeaking = () => Speech.isSpeakingAsync()

type Rec = { start: () => void; stop: () => void; onresult: ((e: any) => void) | null; onend: (() => void) | null; onerror: (() => void) | null; interimResults: boolean; lang: string }

/**
 * Speech to text. The browser has it built in; on a phone it needs a development build with
 * expo-speech-recognition (Expo Go can't do it), so for now the phone falls back to typing.
 */
export function canListen() {
  if (Platform.OS !== 'web' || typeof window === 'undefined') return false
  const w = window as any
  return Boolean(w.SpeechRecognition || w.webkitSpeechRecognition)
}

export function listen(onText: (text: string, final: boolean) => void, onEnd: () => void) {
  const w = window as any
  const R = w.SpeechRecognition || w.webkitSpeechRecognition
  const rec: Rec = new R()
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
