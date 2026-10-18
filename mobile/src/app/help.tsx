import { House, Phone, User } from 'lucide-react-native'
import { useEffect, useState } from 'react'
import { Linking, Pressable, StyleSheet, View } from 'react-native'
import { Card, Empty, Glow, Screen, T, st } from '../components/ui'
import { getProfile } from '../lib/api'
import type { Profile } from '../lib/api'
import { useSettings } from '../lib/settings'
import { C } from '../lib/theme'
import { speak } from '../lib/voice'

export default function Help() {
  const { s: prefs } = useSettings()
  const [p, setP] = useState<Profile | null | undefined>(undefined)
  useEffect(() => { getProfile().then(setP) }, [])
  if (p === undefined) return <Screen title="Get help"><View /></Screen>

  const c = p?.caretaker
  const about = p ? `Your name is ${p.name}. You live at ${p.address}.${c ? ` ${c.name} is ${c.relation}.` : ''}` : ''

  return (
    <Screen title="Get help">
      {c ? (
        <Pressable onPress={() => Linking.openURL(`tel:${c.phone}`)} accessibilityRole="button" accessibilityLabel={`Call ${c.name}`} style={({ pressed }) => pressed && st.pressed}>
          <Glow style={s.call} colors={['#ffe48a', C.help, '#f5b700']}>
            <View style={s.icon}><Phone size={36} color="#b58300" /></View>
            <View style={{ flex: 1 }}>
              <T size={28} weight="semibold">Call {c.name}</T>
              <T size={18} color="#6b5200">{c.relation[0].toUpperCase() + c.relation.slice(1)}</T>
            </View>
          </Glow>
        </Pressable>
      ) : (
        <Empty>Your caretaker hasn't added their phone number yet.</Empty>
      )}

      {p && (
        <Card onPress={() => speak(about, prefs)} label="Read this out loud">
          <T size={15} weight="medium" color={C.muted} style={{ marginBottom: 12 }}>ABOUT YOU · TAP TO HEAR IT</T>
          <View style={s.line}><User size={24} color={C.orangeDeep} /><T size={21} style={{ flex: 1 }}>Your name is <T size={21} weight="semibold">{p.name}</T></T></View>
          <View style={s.line}><House size={24} color={C.orangeDeep} /><T size={21} style={{ flex: 1 }}>You live at <T size={21} weight="semibold">{p.address}</T></T></View>
          {p.notes.map(n => <T key={n} size={19} color={C.ink} style={s.note}>{n}</T>)}
        </Card>
      )}
    </Screen>
  )
}

const s = StyleSheet.create({
  call: { borderRadius: 32, padding: 22, flexDirection: 'row', alignItems: 'center', gap: 18, minHeight: 120 },
  icon: { width: 72, height: 72, borderRadius: 36, backgroundColor: '#fff', alignItems: 'center', justifyContent: 'center' },
  line: { flexDirection: 'row', alignItems: 'center', gap: 14, paddingVertical: 8 },
  note: { paddingTop: 12, marginTop: 8, borderTopWidth: 1, borderTopColor: C.hairline },
})
