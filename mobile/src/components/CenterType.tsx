import { useEffect, useState } from 'react'
import { AccessibilityInfo } from 'react-native'
import { T } from './ui'

/**
 * Text that types itself out from the middle, both ways at once. The whole sentence is laid out
 * from the start (the hidden part is just invisible) so nothing jumps around as it appears.
 */
export function CenterType({ text, size = 22, color = '#fff', speed = 28, weight = 'regular' as const }: { text: string; size?: number; color?: string; speed?: number; weight?: 'regular' | 'medium' }) {
  const [shown, setShown] = useState(0)

  useEffect(() => {
    let id: ReturnType<typeof setInterval> | undefined
    setShown(0)
    AccessibilityInfo.isReduceMotionEnabled().then(still => {
      if (still) return setShown(text.length)
      id = setInterval(() => setShown(n => {
        if (n >= text.length) { clearInterval(id); return n }
        return n + 2
      }), speed)
    })
    return () => clearInterval(id)
  }, [text])

  const mid = text.length / 2
  const a = Math.max(0, Math.floor(mid - shown / 2))
  const b = Math.min(text.length, Math.ceil(mid + shown / 2))
  return (
    <T size={size} weight={weight} color={color} style={{ textAlign: 'center' }} accessibilityLiveRegion="polite" accessibilityLabel={text}>
      <T size={size} weight={weight} color="transparent">{text.slice(0, a)}</T>
      {text.slice(a, b)}
      <T size={size} weight={weight} color="transparent">{text.slice(b)}</T>
    </T>
  )
}
