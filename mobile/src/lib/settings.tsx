import AsyncStorage from '@react-native-async-storage/async-storage'
import { createContext, useContext, useEffect, useState } from 'react'
import type { ReactNode } from 'react'

export interface Settings {
  textScale: number // 1 = normal, up to 1.3
  voiceVolume: number // 0..1, how loud Keepsake speaks
  voiceRate: number // 0.7 slow .. 1 normal
  listenAfterSpeaking: boolean
  assist: Assist // how often Keepsake checks in
  speakFirst: boolean // Keepsake asks "What are you looking for?" when the mic is tapped
}

/** How much help, from less to more: how often Keepsake checks in to ask if they're forgetting something. */
export const ASSIST = ['less', 'normal', 'more'] as const
export type Assist = (typeof ASSIST)[number]

// How often Keepsake checks in, in minutes, for each level (never for less help).
export const CHECK_IN: Record<Assist, number | null> = { less: null, normal: 45, more: 10 }

const DEFAULTS: Settings = { textScale: 1, voiceVolume: 1, voiceRate: 0.85, listenAfterSpeaking: false, assist: 'normal', speakFirst: true }
const KEY = 'keepsake.settings'

const Ctx = createContext<{ s: Settings; set: (p: Partial<Settings>) => void }>({ s: DEFAULTS, set: () => {} })

export function SettingsProvider({ children }: { children: ReactNode }) {
  const [s, setS] = useState(DEFAULTS)
  useEffect(() => {
    AsyncStorage.getItem(KEY).then(v => v && setS(() => {
      const next = { ...DEFAULTS, ...JSON.parse(v) }
      if (!ASSIST.includes(next.assist)) next.assist = DEFAULTS.assist // saved by an older version
      return next
    })).catch(() => {})
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
