import { router } from 'expo-router'
import { useEffect, useRef } from 'react'
import { AccessibilityInfo, Animated, Easing, Image, Platform, Pressable, StyleSheet, useWindowDimensions, View } from 'react-native'
import Svg, { G, Line, Path, Rect, Text as SvgText } from 'react-native-svg'
import { T } from '../components/ui'
import { B, F } from '../lib/theme'

const PANELS = 3
const PLAN_W = 300
const PLAN_H = 380
const native = Platform.OS !== 'web'

/**
 * The opening: a blueprint of their home unfolds panel by panel, the logo settles in, and then it
 * goes to the home screen. Tap to skip. (Not in use right now; the app opens straight on home.)
 */
export default function Intro() {
  const { width, height } = useWindowDimensions()
  const w = Math.min(width - 48, 360)
  const h = (w * PLAN_H) / PLAN_W
  const panel = w / PANELS
  const unfold = useRef([...Array(PANELS)].map(() => new Animated.Value(0))).current
  const logo = useRef(new Animated.Value(0)).current
  const done = useRef(false)

  const go = () => {
    if (done.current) return
    done.current = true
    router.replace('/')
  }

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout>
    AccessibilityInfo.isReduceMotionEnabled().then(still => {
      if (still) {
        unfold.forEach(v => v.setValue(1))
        logo.setValue(1)
        timer = setTimeout(go, 1500)
        return
      }
      Animated.sequence([
        Animated.stagger(380, unfold.map(v => Animated.timing(v, { toValue: 1, duration: 650, easing: Easing.out(Easing.cubic), useNativeDriver: native }))),
        Animated.timing(logo, { toValue: 1, duration: 500, useNativeDriver: native }),
      ]).start()
      timer = setTimeout(go, 3400)
    })
    return () => clearTimeout(timer)
  }, [])

  return (
    <Pressable onPress={go} accessibilityLabel="Skip the intro" style={s.page}>
      <Grid width={width} height={height} />
      <View style={{ width: w, height: h, flexDirection: 'row' }}>
        {unfold.map((v, i) => (
          // Each panel swings open from its left edge, like a folded plan being opened out.
          <Animated.View key={i} style={{
            width: panel, height: h, overflow: 'hidden', transformOrigin: 'left',
            opacity: v.interpolate({ inputRange: [0, 0.15, 1], outputRange: [0, 1, 1] }),
            transform: [{ perspective: 900 }, { rotateY: v.interpolate({ inputRange: [0, 1], outputRange: ['-95deg', '0deg'] }) }],
          }}>
            <View style={{ position: 'absolute', left: -i * panel, top: 0 }}>
              <Plan width={w} height={h} />
            </View>
            {/* A crease shadow on the fold that fades as the panel flattens out. */}
            <Animated.View style={[StyleSheet.absoluteFill, { backgroundColor: B.orange, opacity: v.interpolate({ inputRange: [0, 1], outputRange: [0.35, 0] }) }]} />
          </Animated.View>
        ))}
      </View>
      <Animated.View style={[s.brand, { opacity: logo, transform: [{ translateY: logo.interpolate({ inputRange: [0, 1], outputRange: [12, 0] }) }] }]}>
        <Image source={require('../../assets/icon.png')} style={s.icon} />
        <T size={30} weight="logo" color={B.ink}>keepsake</T>
      </Animated.View>
    </Pressable>
  )
}

/** Graph paper in pale orange. */
function Grid({ width, height }: { width: number; height: number }) {
  const lines = []
  for (let x = 0; x < width; x += 16) lines.push(<Line key={`x${x}`} x1={x} y1={0} x2={x} y2={height} stroke={B.line} strokeWidth={x % 64 === 0 ? 1 : 0.5} strokeOpacity={x % 64 === 0 ? 0.7 : 0.4} />)
  for (let y = 0; y < height; y += 16) lines.push(<Line key={`y${y}`} x1={0} y1={y} x2={width} y2={y} stroke={B.line} strokeWidth={y % 64 === 0 ? 1 : 0.5} strokeOpacity={y % 64 === 0 ? 0.7 : 0.4} />)
  return <Svg width={width} height={height} style={StyleSheet.absoluteFill} pointerEvents="none">{lines}</Svg>
}

/** A blocky floor plan of a small home, with where they walked and where their things are. */
function Plan({ width, height }: { width: number; height: number }) {
  const label = (x: number, y: number, text: string) => (
    <SvgText x={x} y={y} fill={B.orangeDark} fontSize={11} fontFamily={F.medium} letterSpacing={1}>{text.toUpperCase()}</SvgText>
  )
  const pin = (x: number, y: number) => <Rect x={x - 6} y={y - 6} width={12} height={12} fill={B.orange} stroke={B.shadow} strokeWidth={2} />
  return (
    <Svg width={width} height={height} viewBox={`0 0 ${PLAN_W} ${PLAN_H}`}>
      <Rect x={0} y={0} width={PLAN_W} height={PLAN_H} fill="#fffaf2" />
      <G stroke={B.orange} strokeWidth={6} fill="none" strokeLinecap="square">
        <Rect x={14} y={14} width={272} height={352} />
        <Path d="M14,170 H120 M156,170 H286" />
        <Path d="M150,14 V100 M150,136 V170" />
        <Path d="M180,170 V260 M180,296 V366" />
        <Path d="M14,280 H60 M96,280 H180" />
      </G>
      {/* Furniture as plain bricks. */}
      <G fill={B.cream} stroke={B.line} strokeWidth={2}>
        <Rect x={30} y={30} width={100} height={22} />
        <Rect x={196} y={30} width={74} height={50} />
        <Rect x={40} y={200} width={70} height={36} />
        <Rect x={206} y={300} width={60} height={50} />
        <Rect x={196} y={190} width={36} height={60} />
      </G>
      {/* Today's walk, in steps. */}
      <Path d="M78,330 V300 H78 V262 H138 V190 H168 V120 H230 V95" stroke={B.orangeDark} strokeWidth={3} strokeDasharray="6 6" fill="none" />
      {pin(80, 41)}
      {pin(232, 55)}
      {pin(75, 218)}
      {pin(236, 325)}
      {label(28, 160, 'Kitchen')}
      {label(164, 160, 'Bedroom')}
      {label(28, 270, 'Living')}
      {label(196, 286, 'Bath')}
      {label(28, 354, 'Hall')}
    </Svg>
  )
}

const s = StyleSheet.create({
  page: { flex: 1, backgroundColor: '#fffaf2', alignItems: 'center', justifyContent: 'center' },
  brand: { flexDirection: 'row', alignItems: 'center', gap: 12, marginTop: 36 },
  icon: { width: 44, height: 44 },
})
