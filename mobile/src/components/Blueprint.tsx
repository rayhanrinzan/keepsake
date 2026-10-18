import { StyleSheet } from 'react-native'
import Svg, { Defs, Line, RadialGradient, Rect, Stop } from 'react-native-svg'
import { useId } from 'react'
import { P } from '../lib/theme'

/** Blueprint paper: fine white graph lines, a heavier line every fourth square, darker toward the edges. */
export function BlueprintPaper({ width, height }: { width: number; height: number }) {
  const id = useId().replace(/:/g, '')
  const lines = []
  for (let x = 0; x <= width; x += 16) lines.push(<Line key={`x${x}`} x1={x} y1={0} x2={x} y2={height} stroke={P.line} strokeWidth={x % 64 === 0 ? 0.8 : 0.5} strokeOpacity={x % 64 === 0 ? 0.16 : 0.07} />)
  for (let y = 0; y <= height; y += 16) lines.push(<Line key={`y${y}`} x1={0} y1={y} x2={width} y2={y} stroke={P.line} strokeWidth={y % 64 === 0 ? 0.8 : 0.5} strokeOpacity={y % 64 === 0 ? 0.16 : 0.07} />)
  return (
    <Svg width={width} height={height} style={StyleSheet.absoluteFill} pointerEvents="none">
      <Defs>
        <RadialGradient id={`sheet${id}`} cx="50%" cy="40%" r="75%">
          <Stop offset="0" stopColor={P.paper} />
          <Stop offset="1" stopColor={P.paperDeep} />
        </RadialGradient>
      </Defs>
      <Rect x={0} y={0} width={width} height={height} fill={`url(#sheet${id})`} />
      {lines}
    </Svg>
  )
}
