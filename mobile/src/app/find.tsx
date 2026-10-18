import { Search } from 'lucide-react-native'
import { useEffect, useState } from 'react'
import { StyleSheet, TextInput, View } from 'react-native'
import { ItemRow } from '../components/ItemRow'
import { Card, Empty, Screen, T } from '../components/ui'
import { getObjects } from '../lib/api'
import type { TrackedObject } from '../lib/api'
import { useSettings } from '../lib/settings'
import { C, F } from '../lib/theme'
import { speak } from '../lib/voice'

export default function Find() {
  const { s: prefs } = useSettings()
  const [items, setItems] = useState<TrackedObject[] | null>(null)
  const [error, setError] = useState(false)
  const [q, setQ] = useState('')

  useEffect(() => {
    const load = () => getObjects().then(o => { setItems(o); setError(false) }).catch(() => setError(true))
    load()
    const t = setInterval(load, 5000)
    return () => clearInterval(t)
  }, [])

  const shown = (items ?? []).filter(o => o.name.toLowerCase().includes(q.trim().toLowerCase()))

  return (
    <Screen title="Find my things">
      <View style={st.search}>
        <Search size={24} color={C.muted} />
        <TextInput value={q} onChangeText={setQ} placeholder="What are you looking for?" placeholderTextColor={C.muted} style={st.input} />
      </View>
      {error && <Empty>I can't reach your Keepsake right now. I'll keep trying.</Empty>}
      {items && shown.length === 0 && <Empty>{q ? `Nothing called "${q}" yet.` : 'Nothing is being tracked yet.'}</Empty>}
      {shown.map(o => (
        // Tapping an item reads its place out loud.
        <Card key={o.object_id} onPress={() => speak(`${o.name}. ${o.seen ? o.region : 'Not seen yet'}.`, prefs)} label={`${o.name}, ${o.region ?? 'not seen yet'}`}>
          <ItemRow o={o} />
        </Card>
      ))}
      {items && <T size={15} color={C.muted} style={{ textAlign: 'center' }}>Tap a thing to hear where it is.</T>}
    </Screen>
  )
}

const st = StyleSheet.create({
  search: { flexDirection: 'row', alignItems: 'center', gap: 12, borderRadius: 999, backgroundColor: C.sunken, paddingHorizontal: 20, minHeight: 60 },
  input: { flex: 1, fontSize: 19, fontFamily: F.regular, color: C.ink, minHeight: 60 },
})
