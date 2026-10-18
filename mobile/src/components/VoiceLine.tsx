import { useEffect, useRef, useState } from 'react'
import { AccessibilityInfo, useWindowDimensions, View } from 'react-native'
import Svg, { Path } from 'react-native-svg'
import { B } from '../lib/theme'

const STEPS = 28 // blocks across the line
const GRID = 4 // heights snap to this, so the line looks built from bricks

/**
 * The voice line: a stepped, blocky wave that rises and falls with how loud they're speaking.
 * At rest it lies almost flat with a slow ripple.
 */
export function VoiceLine({ level, active, height = 96 }: { level: number; active: boolean; height?: number }) {
  const { width } = useWindowDimensions()
  const w = Math.min(width - 40, 420)
  const [t, setT] = useState(0)
  const still = useRef(false)
  const smooth = useRef(0)

  useEffect(() => {
    AccessibilityInfo.isReduceMotionEnabled().then(v => { still.current = v })
    const id = setInterval(() => setT(x => x + 1), 50)
    return () => clearInterval(id)
  }, [])

  smooth.current += ((active ? level : 0) - smooth.current) * 0.35
  const mid = height / 2
  const amp = still.current ? 0 : Math.max(active ? 0.08 : 0.04, smooth.current) * (mid - 6)
  const step = w / STEPS
  let d = ''
  for (let i = 0; i < STEPS; i++) {
    const edge = Math.sin((Math.PI * (i + 0.5)) / STEPS) // quieter at the ends
    const wave = Math.sin(t * 0.35 + i * 0.75) * 0.65 + Math.sin(t * 0.2 - i * 1.3) * 0.35
    const y = Math.round((mid - amp * edge * wave) / GRID) * GRID
    d += i === 0 ? `M0,${y} H${step}` : ` V${y} H${(i + 1) * step}`
  }
  return (
    <View accessibilityElementsHidden importantForAccessibility="no-hide-descendants">
      <Svg width={w} height={height}>
        <Path d={d} stroke={B.orange} strokeWidth={5} strokeLinejoin="miter" strokeLinecap="square" fill="none" />
      </Svg>
    </View>
  )
}
