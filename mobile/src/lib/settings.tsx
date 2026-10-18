import AsyncStorage from '@react-native-async-storage/async-storage'
import { createContext, useContext, useEffect, useState } from 'react'
import type { ReactNode } from 'react'

export interface Settings {
  textScale: number // 1 = normal, up to 1.3
  voiceVolume: number // 0..1, how loud Keepsake speaks
  voiceRate: number // 0.7 slow .. 1 normal
  listenAfterSpeaking: boolean
  assist: Assist // how much Keepsake leads the conversation
  handsFree: boolean // listen in the background for "where are my keys" (browser only)
  showCamera: boolean // setup only: the live camera feed on the home screen (off for the person using it)
}

/**
 * More help: Keepsake speaks first ("What are you looking for?") and checks in often to ask whether
 * they're forgetting something. Some help: speaks first and checks in now and then. Less help: just
 * listens when they tap the microphone, and never checks in.
 */
export type Assist = 'more' | 'some' | 'less'

// How often Keepsake checks in, in minutes, for each level (none for less help).
export const CHECK_IN: Record<Assist, number | null> = { more: 10, some: 45, less: null }

const DEFAULTS: Settings = { textScale: 1, voiceVolume: 1, voiceRate: 0.85, listenAfterSpeaking: false, assist: 'some', handsFree: true, showCamera: false }
const KEY = 'keepsake.settings'

const Ctx = createContext<{ s: Settings; set: (p: Partial<Settings>) => void }>({ s: DEFAULTS, set: () => {} })

export function SettingsProvider({ children }: { children: ReactNode }) {
  const [s, setS] = useState(DEFAULTS)
  useEffect(() => {
    AsyncStorage.getItem(KEY).then(v => v && setS({ ...DEFAULTS, ...JSON.parse(v) })).catch(() => {})
  }, [])
  const set = (p: Partial<Settings>) =>
    setS(prev => {
      const next = { ...prev, ...p }
      AsyncStorage.setItem(KEY, JSON.stringify(next)).catch(() => {})
      return next
    })
  return <Ctx.Provider value={{ s, set }}>{children}</Ctx.Provider>
}

export const useSettings = () => useContext(Ctx)
