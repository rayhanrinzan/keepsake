import type { ReactNode } from 'react'
import { Pressable, View } from 'react-native'
import type { StyleProp, ViewStyle } from 'react-native'
import { B } from '../lib/theme'

/**
 * A toy brick: a flat colored block sitting on a hard shadow. Pressing it pushes it down onto its
 * shadow, like pressing a real button.
 */
export function Block({ color = B.orangeDark, shadow = B.shadow, border, onPress, label, style, children }: {
  color?: string
  shadow?: string
  border?: string
  onPress?: () => void
  label?: string
  style?: StyleProp<ViewStyle>
  children?: ReactNode
}) {
  const face = (down: boolean) => (
    <View style={{ paddingBottom: B.depth }}>
      <View style={{ position: 'absolute', left: 0, right: 0, top: B.depth, bottom: 0, backgroundColor: shadow, borderRadius: 6 }} />
      <View style={[{ backgroundColor: color, borderRadius: 6, transform: [{ translateY: down ? B.depth - 1 : 0 }] }, border && { borderWidth: 3, borderColor: border }, style]}>
        {children}
      </View>
    </View>
  )
  if (!onPress) return face(false)
  return (
    <Pressable onPress={onPress} accessibilityRole="button" accessibilityLabel={label}>
      {({ pressed }) => face(pressed)}
    </Pressable>
  )
}
