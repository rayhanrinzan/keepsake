import { useEffect, useRef, useState } from 'react'
import { AccessibilityInfo } from 'react-native'
import { T } from './ui'

const FADE = 4 // frames each word takes to fade in

/** '#rrggbb' at the given opacity, since nested text can't take its own opacity on phones. */
function alpha(hex: string, a: number) {
  const n = parseInt(hex.slice(1), 16)
  return `rgba(${n >> 16},${(n >> 8) & 255},${n & 255},${a})`
}

/**
 * Text that writes itself in word by word, each word fading up as the one before it settles, like
 * someone speaking it. The whole sentence is laid out from the start (the words still to come are
 * just invisible) so nothing jumps around. When the text grows (a live transcript), only the new
 * words fade in.
 */
export function CenterType({ text, size = 22, color = '#ffffff', speed = 30, weight = 'regular' }: { text: string; size?: number; color?: string; speed?: number; weight?: 'light' | 'regular' | 'medium' }) {
  const words = text.split(/(\s+)/)
  const count = words.filter(w => w.trim()).length
  const [step, setStep] = useState(0) // how far along, in frames
  const last = useRef('')

  useEffect(() => {
    // Carry on from where it was if this is the same sentence with more on the end.
    const grew = last.current !== '' && text.startsWith(last.current)
    const before = last.current.split(/\s+/).filter(Boolean).length
    last.current = text
    if (!grew) setStep(0)
    else setStep(s => Math.min(s, Math.max(0, before - 1) * 2 + FADE))
    let id: ReturnType<typeof setInterval> | undefined
    AccessibilityInfo.isReduceMotionEnabled().then(still => {
      if (still) return setStep(count * 2 + FADE)
      id = setInterval(() => setStep(s => {
        if (s >= count * 2 + FADE) { clearInterval(id); return s }
        return s + 1
      }), speed)
    })
    return () => clearInterval(id)
  }, [text])

  let k = -1
  return (
    <T size={size} weight={weight} color={color} style={{ textAlign: 'center' }} accessibilityLiveRegion="polite" accessibilityLabel={text}>
      {words.map((w, i) => {
        if (!w.trim()) return w
        k++
        // A new word starts every two frames and takes FADE frames to come in fully.
        const a = Math.max(0, Math.min(1, (step - k * 2) / FADE))
        return <T key={i} size={size} weight={weight} color={alpha(color, a)}>{w}</T>
      })}
    </T>
  )
}
