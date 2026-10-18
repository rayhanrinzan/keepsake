import { router, useLocalSearchParams } from 'expo-router'
import { ChevronLeft, Clock } from 'lucide-react-native'
import { useEffect, useState } from 'react'
import { Image, Pressable, ScrollView, StyleSheet, View } from 'react-native'
import { useSafeAreaInsets } from 'react-native-safe-area-context'
import { CenterType } from '../../components/CenterType'
import { T } from '../../components/ui'
import { ago, getObjects, imageUrl, where } from '../../lib/api'
import type { TrackedObject } from '../../lib/api'
import { itemPhoto } from '../../lib/items'
import { useSettings } from '../../lib/settings'
import { P } from '../../lib/theme'
import { speak } from '../../lib/voice'

/** Grounded like the web app: when it was last seen and the photo, never a room location. */
function sentence(o: TrackedObject) {
  if (!o.seen) return `I haven't seen your ${o.name.toLowerCase()} yet.`
  const plural = o.name.endsWith('s')
  const noun = o.name.toLowerCase()
  if (o.visible) return `Your ${noun} ${plural ? 'are' : 'is'} in view right now.`
  const photo = o.snapshot ? ' Here is the last photo.' : ''
  return `I last saw your ${noun} ${ago(o.last_seen)}.${photo} ${plural ? 'They' : 'It'} may have moved since.`
}

/** Locate one item: says where it is out loud as soon as it opens, and types it out as it speaks. */
export default function Locate() {
  const { id } = useLocalSearchParams<{ id: string }>()
  const inset = useSafeAreaInsets()
  const { s: prefs } = useSettings()
  const [o, setO] = useState<TrackedObject | null | undefined>(undefined)
  const [round, setRound] = useState(0)
  const [snap, setSnap] = useState(true) // the real last photo first, when there is one

  function sayIt(item: TrackedObject) {
    setRound(r => r + 1)
    speak(sentence(item), prefs)
  }

  useEffect(() => {
    getObjects()
      .then(list => {
        const found = list.find(x => x.object_id === id) ?? null
        setO(found)
        if (found) sayIt(found)
      })
      .catch(() => setO(null))
  }, [id])

  return (
    <View style={s.page}>
      <ScrollView contentContainerStyle={[s.body, { paddingTop: inset.top + 16, paddingBottom: inset.bottom + 32 }]} showsVerticalScrollIndicator={false}>
        <View style={s.head}>
          <Pressable onPress={() => (router.canGoBack() ? router.back() : router.replace('/'))} accessibilityRole="button" accessibilityLabel="Back to my items" style={({ pressed }) => [s.back, pressed && s.pressed]}>
            <ChevronLeft size={20} color={P.line} />
            <T size={16} weight="medium" color={P.line}>My Items</T>
          </Pressable>
          <Image source={require('../../../assets/inside-icon.png')} style={s.logo} accessibilityLabel="Keepsake" resizeMode="contain" />
        </View>

        {o === null && <T size={20} color={P.line} style={{ textAlign: 'center', marginTop: 80 }}>I can't find that item right now.</T>}
        {o && (
          <>
            <View style={s.hero}>
              {/* The last picture the camera took of it, when there is one; tap to swap with the item's picture. */}
              <Pressable onPress={() => o.snapshot && setSnap(v => !v)} disabled={!o.snapshot} accessibilityRole={o.snapshot ? 'button' : undefined}
                accessibilityLabel={o.snapshot ? (snap ? `Show the picture of your ${o.name.toLowerCase()}` : `Show the last photo of your ${o.name.toLowerCase()}`) : undefined}
                style={[s.frame, snap && s.frameSnap]}>
                {snap && o.snapshot
                  ? <Image source={{ uri: imageUrl(o.snapshot.image_url) }} style={StyleSheet.absoluteFill} resizeMode="cover" accessibilityLabel={`Last photo of your ${o.name.toLowerCase()}`} />
                  : <Image source={itemPhoto(o.icon)} style={s.photo} resizeMode="contain" />}
              </Pressable>
              <T size={34} weight="medium" color={P.line}>{o.name}</T>
              <View style={s.place}>
                <Clock size={18} color={P.soft} />
                <T size={18} color={P.soft}>{where(o)}</T>
              </View>
            </View>
            <View style={s.said}>
              <CenterType key={round} text={sentence(o)} size={24} color={P.line} />
            </View>
          </>
        )}
      </ScrollView>
    </View>
  )
}

const s = StyleSheet.create({
  page: { flex: 1, backgroundColor: '#000000' },
  body: { paddingHorizontal: 22, gap: 24 },
  head: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  back: { flexDirection: 'row', alignItems: 'center', gap: 4, height: 42, paddingLeft: 8, paddingRight: 16, borderWidth: 1, borderColor: P.faint, borderRadius: P.radius },
  pressed: { backgroundColor: 'rgba(255,255,255,0.12)' },
  logo: { width: 40, height: 22 },
  hero: { alignItems: 'center', gap: 14, marginTop: 36 },
  frame: { width: 240, height: 160, alignItems: 'center', justifyContent: 'center', backgroundColor: 'rgba(255,255,255,0.92)', borderRadius: P.radius, overflow: 'hidden' },
  frameSnap: { width: '100%', height: undefined, aspectRatio: 4 / 3 },
  place: { flexDirection: 'row', alignItems: 'center', gap: 6, marginTop: -6 },
  photo: { width: 190, height: 120 },
  said: { minHeight: 96, justifyContent: 'center', paddingHorizontal: 6 },
})
