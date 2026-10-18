import { useEffect, useRef, useState } from 'react'
import { Image, StyleSheet, View } from 'react-native'
import { getHealth, imageUrl, SAMPLE } from '../lib/api'
import type { Health } from '../lib/api'
import { P } from '../lib/theme'
import { T } from './ui'

const FRAME_MS = 200 // ~5 fps, the backend's inference rate
const HEALTH_MS = 2000

/**
 * Setup view of the worn camera: the backend's newest annotated frame, polled like the web app's feed
 * (single JPEGs recover on their own where an MJPEG stream stalls), plus its status line. Each frame
 * loads underneath the one on screen and swaps in once loaded, so the picture never flashes blank.
 */
export function LiveCamera() {
  const [shown, setShown] = useState<string | null>(null)
  const [next, setNext] = useState<string | null>(null)
  const [health, setHealth] = useState<Health | null>(null)
  const [down, setDown] = useState(false)
  const n = useRef(0)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const alive = useRef(true)

  const fetchNext = (delay: number) => {
    if (timer.current) clearTimeout(timer.current)
    timer.current = setTimeout(() => {
      if (alive.current) setNext(imageUrl(`/api/camera/frame?n=${++n.current}`))
    }, delay)
  }

  useEffect(() => {
    alive.current = true
    if (SAMPLE) return
    fetchNext(0)
    const poll = () => getHealth().then(h => { setHealth(h); setDown(false) }).catch(() => setDown(true))
    poll()
    const id = setInterval(poll, HEALTH_MS)
    return () => {
      alive.current = false
      clearInterval(id)
      if (timer.current) clearTimeout(timer.current)
    }
  }, [])

  const status = SAMPLE ? 'No camera in sample mode'
    : down ? "Can't reach the Keepsake backend"
    : !health ? 'Connecting…'
    : health.error ?? health.warning ?? `Camera ${health.camera} · ${health.fps.toFixed(0)} fps`
  const ok = !SAMPLE && !down && health?.camera === 'active' && !health.warning && !health.error

  return (
    <View style={s.wrap} accessibilityLabel="Live camera feed, for setup">
      <View style={s.frame}>
        {shown && <Image source={{ uri: shown }} style={StyleSheet.absoluteFill} resizeMode="contain" />}
        {next && next !== shown && (
          <Image source={{ uri: next }} style={[StyleSheet.absoluteFill, s.loading]} resizeMode="contain"
            onLoad={() => { setShown(next); fetchNext(FRAME_MS) }}
            onError={() => fetchNext(1000)} />
        )}
        {!shown && <T size={14} color={P.soft}>{SAMPLE ? 'Sample mode' : 'Waiting for the camera…'}</T>}
      </View>
      <View style={s.status}>
        <View style={[s.dot, { backgroundColor: ok ? '#3ddc97' : '#ffb27a' }]} />
        <T size={13} color="#6b6b6b" numberOfLines={2} style={{ flex: 1 }}>{status}</T>
      </View>
    </View>
  )
}

const s = StyleSheet.create({
  wrap: { marginBottom: 28, gap: 10 },
  frame: { width: '100%', aspectRatio: 16 / 9, backgroundColor: '#000', borderRadius: P.radius, overflow: 'hidden', alignItems: 'center', justifyContent: 'center' },
  loading: { opacity: 0 },
  status: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  dot: { width: 8, height: 8, borderRadius: 4 },
})
