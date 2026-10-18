import { router, useLocalSearchParams } from 'expo-router'
import { ChevronLeft, Volume2 } from 'lucide-react-native'
import { useEffect, useState } from 'react'
import { Image, ScrollView, StyleSheet, useWindowDimensions, View } from 'react-native'
import { useSafeAreaInsets } from 'react-native-safe-area-context'
import { Aura } from '../../components/Aura'
import { CenterType } from '../../components/CenterType'
import { GlassPill } from '../../components/GlassPill'
import { T } from '../../components/ui'
import { ago, getObjects, imageUrl } from '../../lib/api'
import type { TrackedObject } from '../../lib/api'
import { itemPhoto } from '../../lib/items'
import { useSettings } from '../../lib/settings'
import { O } from '../../lib/theme'
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
  const { height: h } = useWindowDimensions()
  const { s: prefs } = useSettings()
  const [o, setO] = useState<TrackedObject | null | undefined>(undefined)
  const [talking, setTalking] = useState(false)
  const [round, setRound] = useState(0)

  function sayIt(item: TrackedObject) {
    setTalking(true)
    setRound(r => r + 1)
    const text = sentence(item)
    speak(text, prefs, () => setTalking(false))
    setTimeout(() => setTalking(false), 900 + text.length * 65)
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
      <Aura height={h * 0.5} center={h * 0.27} energy={talking ? 0.35 : 0} strength={0.6} />
      <ScrollView contentContainerStyle={[s.body, { paddingTop: inset.top + 16, paddingBottom: inset.bottom + 32 }]} showsVerticalScrollIndicator={false}>
        <View style={s.head}>
          <GlassPill onPress={() => (router.canGoBack() ? router.back() : router.replace('/'))} label="Back to my items" style={s.back}>
            <ChevronLeft size={22} color={O.text} />
            <T size={16} weight="medium" color={O.text}>My Items</T>
          </GlassPill>
          <Image source={require('../../../assets/inside-icon.png')} style={s.logo} accessibilityLabel="Keepsake" resizeMode="contain" />
        </View>

        {o === null && <T size={20} color={O.text} style={{ textAlign: 'center', marginTop: 80 }}>I can't find that item right now.</T>}
        {o && (
          <>
            <View style={s.hero}>
              <Image source={itemPhoto(o.icon)} style={s.photo} resizeMode="contain" />
              <T size={34} weight="medium" color={O.text}>{o.name}</T>
            </View>
            <View style={s.said}>
              <CenterType key={round} text={sentence(o)} size={24} color={O.text} />
            </View>
            {o.snapshot && (
              <Image source={{ uri: imageUrl(o.snapshot.image_url) }} style={s.snap} accessibilityLabel={`Last photo of your ${o.name.toLowerCase()}`} />
            )}
            <GlassPill onPress={() => sayIt(o)} label="Say it again" style={s.again}>
              <Volume2 size={22} color={O.text} />
              <T size={18} weight="medium" color={O.text}>Say it again</T>
            </GlassPill>
          </>
        )}
      </ScrollView>
    </View>
  )
}

const s = StyleSheet.create({
  page: { flex: 1, backgroundColor: O.page },
  body: { paddingHorizontal: 22, gap: 24 },
  head: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  back: { flexDirection: 'row', alignItems: 'center', gap: 4, height: 44, paddingLeft: 10, paddingRight: 18 },
  logo: { width: 40, height: 22 },
  hero: { alignItems: 'center', gap: 6, marginTop: 40 },
  photo: { width: 200, height: 130 },
  said: { minHeight: 96, justifyContent: 'center', paddingHorizontal: 6 },
  snap: { width: '100%', aspectRatio: 4 / 3, borderRadius: 28, borderWidth: 1, borderColor: O.rim },
  again: { flexDirection: 'row', alignItems: 'center', gap: 10, alignSelf: 'center', height: 54, paddingHorizontal: 26 },
})
