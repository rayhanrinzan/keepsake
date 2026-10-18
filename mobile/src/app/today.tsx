import { Check } from 'lucide-react-native'
import { useEffect, useState } from 'react'
import { StyleSheet, View } from 'react-native'
import { Card, Empty, Screen, T } from '../components/ui'
import { getReminders } from '../lib/api'
import type { Reminder } from '../lib/api'
import { useSettings } from '../lib/settings'
import { C } from '../lib/theme'
import { speak } from '../lib/voice'

export default function Today() {
  const { s: prefs } = useSettings()
  const [list, setList] = useState<Reminder[] | null>(null)
  useEffect(() => { getReminders().then(setList) }, [])

  return (
    <Screen title="Today">
      {list && list.length === 0 && <Empty>Nothing to remember right now. Enjoy your day.</Empty>}
      {list?.map(r => (
        <Card key={r.id} onPress={() => speak(`At ${r.time}. ${r.title}. ${r.detail ?? ''}`, prefs)} label={`${r.time}, ${r.title}`} style={[st.row, r.done && { opacity: 0.55 }]}>
          <View style={[st.check, r.done && st.done]}>{r.done && <Check size={22} color="#fff" strokeWidth={3} />}</View>
          <View style={{ flex: 1 }}>
            <T size={16} weight="medium" color={C.orangeDeep}>{r.time}</T>
            <T size={22} weight="semibold">{r.title}</T>
            {r.detail && <T size={18} color={C.muted}>{r.detail}</T>}
          </View>
        </Card>
      ))}
    </Screen>
  )
}

const st = StyleSheet.create({
  row: { flexDirection: 'row', gap: 16, alignItems: 'flex-start' },
  check: { width: 36, height: 36, borderRadius: 18, borderWidth: 2, borderColor: C.hairline, alignItems: 'center', justifyContent: 'center', marginTop: 4 },
  done: { backgroundColor: C.live, borderColor: C.live },
})
