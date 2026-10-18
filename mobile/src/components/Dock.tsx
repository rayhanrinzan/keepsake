import { router } from 'expo-router'
import { CalendarDays, LifeBuoy } from 'lucide-react-native'
import { Pressable, StyleSheet, View } from 'react-native'
import { useSafeAreaInsets } from 'react-native-safe-area-context'
import { C } from '../lib/theme'
import { Blob } from './Blob'
import { Glass } from './Glass'
import { T, st } from './ui'

/** Glass bar at the bottom: Help, the speak blob in the middle, Today. */
export function Dock() {
  const inset = useSafeAreaInsets()
  return (
    <View style={[s.wrap, { bottom: inset.bottom + 16 }]} pointerEvents="box-none">
      <Glass strong style={s.bar}>
        <Pressable onPress={() => router.push('/help')} accessibilityRole="button" accessibilityLabel="Help" style={({ pressed }) => [s.link, pressed && st.pressed]}>
          <LifeBuoy size={24} color={C.ink} />
          <T size={15} weight="round">Help</T>
        </Pressable>
        <View style={{ width: 110 }} />
        <Pressable onPress={() => router.push('/today')} accessibilityRole="button" accessibilityLabel="Today" style={({ pressed }) => [s.link, pressed && st.pressed]}>
          <CalendarDays size={24} color={C.ink} />
          <T size={15} weight="round">Today</T>
        </Pressable>
      </Glass>
      <Pressable onPress={() => router.push('/talk')} accessibilityRole="button" accessibilityLabel="Speak to Keepsake" style={({ pressed }) => [s.speak, pressed && st.pressed]}>
        <Blob />
        <T size={14} weight="round" color={C.muted} style={{ marginTop: 4 }}>speak</T>
      </Pressable>
    </View>
  )
}

const s = StyleSheet.create({
  wrap: { position: 'absolute', left: 20, right: 20, alignItems: 'center' },
  bar: { flexDirection: 'row', alignSelf: 'stretch', height: 72, alignItems: 'center', paddingHorizontal: 12 },
  link: { alignItems: 'center', flex: 1 },
  speak: { position: 'absolute', bottom: 2, alignItems: 'center' },
})
