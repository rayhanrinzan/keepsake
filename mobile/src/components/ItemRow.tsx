import { Image, StyleSheet, View } from 'react-native'
import { ago, imageUrl, where } from '../lib/api'
import type { TrackedObject } from '../lib/api'
import { itemPic } from '../lib/items'
import { C } from '../lib/theme'
import { T } from './ui'

/** Photo (or icon), name, where it is and how long ago. */
export function ItemRow({ o }: { o: TrackedObject }) {
  return (
    <View style={s.row}>
      <View style={s.photo}>
        {o.snapshot ? <Image source={{ uri: imageUrl(o.snapshot.image_url) }} style={StyleSheet.absoluteFill} /> : <Image source={itemPic(o.icon)} style={{ width: 48, height: 48 }} resizeMode="contain" />}
      </View>
      <View style={{ flex: 1 }}>
        <T size={21} weight="semibold">{o.name}</T>
        <View style={s.where}>
          {o.seen && <View style={[s.dot, { backgroundColor: o.visible ? C.live : C.orange }]} />}
          <T size={17} color={C.muted} style={{ flexShrink: 1 }}>{where(o)}</T>
        </View>
        {o.last_seen && !o.visible && <T size={15} color={C.muted}>{ago(o.last_seen)}</T>}
      </View>
    </View>
  )
}

const s = StyleSheet.create({
  row: { flexDirection: 'row', alignItems: 'center', gap: 16 },
  photo: { width: 64, height: 64, borderRadius: 18, overflow: 'hidden', backgroundColor: 'rgba(255,255,255,0.55)', alignItems: 'center', justifyContent: 'center' },
  where: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  dot: { width: 10, height: 10, borderRadius: 5 },
})
