import { router } from 'expo-router'
import { ChevronUp } from 'lucide-react-native'
import { useRef } from 'react'
import { Animated, Image, PanResponder, Pressable, ScrollView, StyleSheet, useWindowDimensions, View } from 'react-native'
import { useSafeAreaInsets } from 'react-native-safe-area-context'
import Svg, { Circle, Defs, Path, RadialGradient, Rect, Stop } from 'react-native-svg'
import { where } from '../lib/api'
import type { TrackedObject } from '../lib/api'
import { itemPic } from '../lib/items'
import { C } from '../lib/theme'
import { Glass } from './Glass'
import { Empty, T, st } from './ui'

/**
 * The black pull-up panel with their things in a column of glass ovals. It rests low so the voice assistant
 * has room; drag the notch at the top (or tap its arrow) to pull it up over the white part.
 */
export function ItemSheet({ items, error, top }: { items: TrackedObject[] | null; error: boolean; top: number }) {
  const { width: w, height: h } = useWindowDimensions()
  const inset = useSafeAreaInsets()
  const low = h - top // how far down the panel rests
  const high = inset.top + 24
  const travel = low - high
  const y = useRef(new Animated.Value(travel)).current
  const at = useRef(travel)
  y.addListener(({ value }) => { at.current = value })

  const snap = (open: boolean) => Animated.spring(y, { toValue: open ? 0 : travel, useNativeDriver: false, bounciness: 4 }).start()
  const pan = useRef(PanResponder.create({
    onMoveShouldSetPanResponder: (_, g) => Math.abs(g.dy) > 6,
    onPanResponderGrant: () => { y.setOffset(at.current); y.setValue(0) },
    onPanResponderMove: (_, g) => y.setValue(Math.max(-at.current, Math.min(travel - at.current, g.dy))),
    onPanResponderRelease: (_, g) => {
      y.flattenOffset()
      snap(g.vy < -0.3 || (g.vy < 0.3 && at.current < travel / 2))
    },
  })).current

  // The panel's top edge: rounded corners and a notch in the middle that holds the arrow.
  const H = h - high
  const R = 32
  const a = w / 2 - NOTCH / 2 - 18
  const b = w / 2 + NOTCH / 2 + 18
  const edge = `M0,${R} A${R},${R} 0 0 1 ${R},0 L${a},0 C${a + 14},0 ${a + 10},${DIP} ${a + 30},${DIP} L${b - 30},${DIP} C${b - 10},${DIP} ${b - 14},0 ${b},0 L${w - R},0 A${R},${R} 0 0 1 ${w},${R} L${w},${H} L0,${H} Z`

  const rotate = y.interpolate({ inputRange: [0, travel], outputRange: ['180deg', '0deg'] })

  return (
    <Animated.View style={[s.sheet, { top: high, height: H, transform: [{ translateY: y }] }]}>
      <Svg width={w} height={H} style={StyleSheet.absoluteFill} pointerEvents="none">
        {/* White behind the corners and the notch, so nothing from the page shows through when it's pulled up. */}
        <Rect x={0} y={0} width={w} height={R} fill="#fff" />
        <Path d={edge} fill="#000" />
      </Svg>
      <View {...pan.panHandlers}>
        <Pressable onPress={() => snap(at.current > travel / 2)} accessibilityRole="button" accessibilityLabel="Show all my things" style={s.tab}>
          <Animated.View style={{ transform: [{ rotate }] }}><ChevronUp size={24} color={C.ink} /></Animated.View>
        </Pressable>
        <View style={s.head}>
          <T size={28} color="#fff">My things</T>
        </View>
      </View>

      <ScrollView contentContainerStyle={[s.list, { paddingBottom: inset.bottom + 40 }]} showsVerticalScrollIndicator={false}>
        {error && <Empty>I can't reach your Keepsake right now. I'll keep trying.</Empty>}
        {items && items.length === 0 && <Empty>Nothing is being tracked yet.</Empty>}
        {items?.map(o => (
          <Pressable key={o.object_id} onPress={() => router.push({ pathname: '/item/[id]', params: { id: o.object_id } })} accessibilityRole="button" accessibilityLabel={`${o.name}. ${where(o)}. Tap to locate.`} style={({ pressed }) => pressed && st.pressed}>
            <Glass dark style={[s.card, !o.seen && { opacity: 0.55 }]}>
              {/* A faint pool of light under the picture so dark things like glasses still show. */}
              <View style={s.picBox}>
                <Svg width={84} height={84} style={s.halo} pointerEvents="none">
                  <Defs>
                    <RadialGradient id="itemHalo" cx="50%" cy="50%" r="50%">
                      <Stop offset="0" stopColor="#ffffff" stopOpacity="0.38" />
                      <Stop offset="1" stopColor="#ffffff" stopOpacity="0" />
                    </RadialGradient>
                  </Defs>
                  <Circle cx={42} cy={42} r={42} fill="url(#itemHalo)" />
                </Svg>
                <Image source={itemPic(o.icon)} style={s.pic} resizeMode="contain" />
              </View>
              <View style={s.text}>
                <T size={22} color="#fff" numberOfLines={1}>{o.name}</T>
                <View style={s.where}>
                  {o.seen && <View style={[s.dot, { backgroundColor: o.visible ? '#3ddc97' : C.orange }]} />}
                  <T size={16} weight="round" color="rgba(255,255,255,0.7)" numberOfLines={1} style={{ flexShrink: 1 }}>{where(o)}</T>
                </View>
              </View>
            </Glass>
          </Pressable>
        ))}
      </ScrollView>
    </Animated.View>
  )
}

const NOTCH = 96 // width of the flat bottom of the notch
const DIP = 26 // how deep the notch goes

const s = StyleSheet.create({
  sheet: { position: 'absolute', left: 0, right: 0, userSelect: 'none', overflow: 'hidden' },
  tab: { alignSelf: 'center', width: NOTCH, height: DIP, alignItems: 'center', justifyContent: 'center' },
  head: { paddingHorizontal: 22, paddingTop: 4, paddingBottom: 14 },
  list: { gap: 16, paddingHorizontal: 16, paddingTop: 4 },
  card: { flexDirection: 'row', alignItems: 'center', gap: 18, padding: 16, paddingRight: 32 },
  picBox: { width: 72, height: 64, marginLeft: 4, alignItems: 'center', justifyContent: 'center' },
  halo: { position: 'absolute', left: -6, top: -10 },
  pic: { width: 64, height: 60 },
  text: { flex: 1, gap: 4 },
  where: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  dot: { width: 8, height: 8, borderRadius: 4 },
})
