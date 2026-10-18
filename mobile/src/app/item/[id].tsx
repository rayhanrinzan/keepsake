import { router, useLocalSearchParams } from 'expo-router'
import { ChevronLeft, Clock, Volume2 } from 'lucide-react-native'
import { useEffect, useRef, useState } from 'react'
import { Image, Pressable, ScrollView, StyleSheet, View } from 'react-native'
import { useSafeAreaInsets } from 'react-native-safe-area-context'
import { CenterType } from '../../components/CenterType'
import { BoxedPhoto, Thumb } from '../../components/Photo'
import { T } from '../../components/ui'
import { ago, ask, EVENT_LABEL, fullTime, getObjects, getSnapshots, where } from '../../lib/api'
import type { Snapshot, TrackedObject } from '../../lib/api'
import { itemPhoto } from '../../lib/items'
import { useSettings } from '../../lib/settings'
import { P } from '../../lib/theme'
import { speak, stopSpeaking } from '../../lib/voice'

/** Said straight away from what the app already knows; replaced by Keepsake's own answer, which adds
 *  Amanda's description of what's around the item in its last photo. */
function sentence(o: TrackedObject) {
  if (!o.seen) return `I haven't seen your ${o.name.toLowerCase()} yet.`
  const plural = o.name.endsWith('s')
  const noun = o.name.toLowerCase()
  if (o.visible) return `Your ${noun} ${plural ? 'are' : 'is'} in view right now.`
  const photo = o.snapshot ? ' Here is the last photo.' : ''
  return `I last saw your ${noun} ${ago(o.last_seen)}.${photo} ${plural ? 'They' : 'It'} may have moved since.`
}

/** Locate one item: says where it was last seen (with the description), shows the photo with the item
 *  boxed, and the earlier photos. */
export default function Locate() {
  const { id } = useLocalSearchParams<{ id: string }>()
  const inset = useSafeAreaInsets()
  const { s: prefs } = useSettings()
  const [o, setO] = useState<TrackedObject | null | undefined>(undefined)
  const [text, setText] = useState('')
  const [checking, setChecking] = useState(false)
  const [round, setRound] = useState(0)
  const [history, setHistory] = useState<Snapshot[]>([])
  const [picked, setPicked] = useState<number | null>(null)
  const [showPicture, setShowPicture] = useState(false)
  const alive = useRef(true)

  function sayIt(t: string) {
    setText(t)
    setRound(r => r + 1)
    speak(t, prefs)
  }

  async function lookUp(item: TrackedObject) {
    if (!item.seen) return sayIt(sentence(item))
    setText(sentence(item))
    setChecking(true)
    try {
      const a = await ask(`where is my ${item.name.toLowerCase()}`)
      if (alive.current) sayIt(a.answer)
    } catch {
      if (alive.current) sayIt(sentence(item))
    }
    if (alive.current) setChecking(false)
  }

  useEffect(() => {
    alive.current = true
    getObjects()
      .then(list => {
        const found = list.find(x => x.object_id === id) ?? null
        setO(found)
        if (found) {
          lookUp(found)
          if (found.seen) getSnapshots(found.object_id).then(setHistory).catch(() => setHistory([]))
        }
      })
      .catch(() => setO(null))
    return () => { alive.current = false; stopSpeaking() }
  }, [id])

  const latest = o?.snapshot ?? null
  const shown = history.find(h => h.id === picked) ?? latest
  const isLatest = !shown || shown.id === latest?.id
  const when = isLatest ? o?.last_seen : shown?.timestamp

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
              {/* The last photo with the item boxed; tap to swap with the item's picture. */}
              {shown && !showPicture ? (
                <Pressable onPress={() => setShowPicture(true)} accessibilityRole="button" accessibilityLabel={`Show the picture of your ${o.name.toLowerCase()}`} style={{ width: '100%' }}>
                  <BoxedPhoto snapshot={shown} alt={`${isLatest ? 'Last photo' : 'Earlier photo'} of your ${o.name.toLowerCase()}`} />
                </Pressable>
              ) : (
                <Pressable onPress={() => setShowPicture(false)} disabled={!shown} accessibilityRole={shown ? 'button' : undefined}
                  accessibilityLabel={shown ? `Show the last photo of your ${o.name.toLowerCase()}` : undefined} style={s.frame}>
                  <Image source={itemPhoto(o.icon)} style={s.photo} resizeMode="contain" />
                </Pressable>
              )}
              <T size={34} weight="medium" color={P.line}>{o.name}</T>
              <View style={s.place}>
                <Clock size={18} color={P.soft} />
                <T size={18} color={P.soft}>{isLatest ? where(o) : `Photo taken ${ago(shown?.timestamp ?? null)}`}</T>
              </View>
              {when && <T size={14} weight="round" color={P.faint}>{fullTime(when)}</T>}
            </View>

            <View style={s.said}>
              {text !== '' && <CenterType key={round} text={text} size={22} color={P.line} />}
              {checking && <T size={14} weight="round" color={P.soft} style={{ textAlign: 'center', marginTop: 8 }}>Looking at the photo…</T>}
            </View>

            {!o.seen && (
              <T size={16} color={P.soft} style={{ textAlign: 'center' }}>
                Put your {o.name.toLowerCase()} where the camera can see it. Keepsake will remember it with a photo.
              </T>
            )}

            {o.seen && (
              <Pressable onPress={() => sayIt(text || sentence(o))} accessibilityRole="button" accessibilityLabel="Say it again" style={({ pressed }) => [s.again, pressed && s.pressed]}>
                <Volume2 size={20} color={P.line} />
                <T size={16} weight="medium" color={P.line}>Say it again</T>
              </Pressable>
            )}

            {history.length > 1 && (
              <View style={{ gap: 12 }}>
                <T size={14} color={P.soft}>Earlier photos</T>
                <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 12 }}>
                  {history.map(h => {
                    const on = shown?.id === h.id
                    return (
                      <Pressable key={h.id} onPress={() => { setPicked(h.id); setShowPicture(false) }} accessibilityRole="button" accessibilityState={{ selected: on }}
                        accessibilityLabel={`${EVENT_LABEL[h.event_type] ?? 'Seen'}, ${fullTime(h.timestamp)}`} style={{ width: 128, gap: 6 }}>
                        <View style={[s.thumbRing, on && s.thumbOn]}>
                          <Thumb snapshot={h} width={122} height={92} alt="" />
                        </View>
                        <T size={13} weight="medium" color={P.line} numberOfLines={1}>{EVENT_LABEL[h.event_type] ?? 'Seen'}</T>
                        <T size={12} weight="round" color={P.soft}>{ago(h.timestamp)}</T>
                      </Pressable>
                    )
                  })}
                </ScrollView>
              </View>
            )}
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
  hero: { alignItems: 'center', gap: 12, marginTop: 24 },
  frame: { width: 240, height: 160, alignItems: 'center', justifyContent: 'center', backgroundColor: 'rgba(255,255,255,0.92)', borderRadius: P.radius, overflow: 'hidden' },
  place: { flexDirection: 'row', alignItems: 'center', gap: 6, marginTop: -4 },
  photo: { width: 190, height: 120 },
  said: { minHeight: 96, justifyContent: 'center', paddingHorizontal: 6 },
  again: { flexDirection: 'row', alignItems: 'center', gap: 8, alignSelf: 'center', height: 44, paddingHorizontal: 18, borderWidth: 1, borderColor: P.faint, borderRadius: P.radius },
  thumbRing: { padding: 2, borderRadius: P.radius + 2, borderWidth: 1, borderColor: 'transparent' },
  thumbOn: { borderColor: '#ffffff' },
})
