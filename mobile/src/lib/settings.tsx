import AsyncStorage from '@react-native-async-storage/async-storage'
import { createContext, useContext, useEffect, useState } from 'react'
import type { ReactNode } from 'react'

export interface Settings {
  textScale: number // 1 = normal, up to 1.3
  voiceVolume: number // 0..1, how loud Keepsake speaks
  voiceRate: number // 0.7 slow .. 1 normal
  listenAfterSpeaking: boolean
}

const DEFAULTS: Settings = { textScale: 1, voiceVolume: 1, voiceRate: 0.85, listenAfterSpeaking: false }
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
