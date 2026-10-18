import { useState } from 'react'
import { Image, StyleSheet, View } from 'react-native'
import type { StyleProp, ViewStyle } from 'react-native'
import { imageUrl } from '../lib/api'
import type { Snapshot } from '../lib/api'
import { P } from '../lib/theme'

const RATIO = 16 / 9 // the camera's photos are 1280×720
const DIM = 'rgba(0,0,0,0.25)'

/** The whole photo with the item marked, like the web app: a white box, the rest dimmed a little. */
export function BoxedPhoto({ snapshot, alt, style }: { snapshot: Snapshot; alt: string; style?: StyleProp<ViewStyle> }) {
  const [ratio, setRatio] = useState(RATIO)
  const [x0, y0, x1, y1] = snapshot.bbox
  const pct = (v: number) => `${Math.max(0, Math.min(1, v)) * 100}%` as const
  return (
    <View style={[s.frame, { aspectRatio: ratio }, style]}>
      <Image source={{ uri: imageUrl(snapshot.image_url) }} style={StyleSheet.absoluteFill} resizeMode="cover" accessibilityLabel={alt}
        onLoad={e => { const src = e.nativeEvent?.source; if (src?.width && src?.height) setRatio(src.width / src.height) }} />
      {/* Dim around the box: above, below, left and right of it. */}
      <View pointerEvents="none" style={[s.dim, { left: 0, right: 0, top: 0, height: pct(y0) }]} />
      <View pointerEvents="none" style={[s.dim, { left: 0, right: 0, top: pct(y1), bottom: 0 }]} />
      <View pointerEvents="none" style={[s.dim, { left: 0, width: pct(x0), top: pct(y0), height: pct(y1 - y0) }]} />
      <View pointerEvents="none" style={[s.dim, { left: pct(x1), right: 0, top: pct(y0), height: pct(y1 - y0) }]} />
      <View pointerEvents="none" style={[s.box, { left: pct(x0), top: pct(y0), width: pct(x1 - x0), height: pct(y1 - y0) }]} />
    </View>
  )
}

/** A small crop of the photo centred on the item, for lists (the web app's thumbnails). */
export function Thumb({ snapshot, width, height, alt }: { snapshot: Snapshot; width: number; height: number; alt: string }) {
  const [x0, y0, x1, y1] = snapshot.bbox
  const cover = Math.max(width, height * RATIO) // smallest image width that still fills the thumb
  // Zoom in so the item fills about three quarters of the thumbnail, but never past 4× the cover size.
  const fit = Math.min((0.75 * width) / Math.max(0.01, x1 - x0), (0.75 * height * RATIO) / Math.max(0.01, y1 - y0))
  const iw = Math.min(cover * 4, Math.max(cover, fit))
  const ih = iw / RATIO
  const left = Math.min(0, Math.max(width - iw, width / 2 - ((x0 + x1) / 2) * iw))
  const top = Math.min(0, Math.max(height - ih, height / 2 - ((y0 + y1) / 2) * ih))
  return (
    <View style={[s.thumb, { width, height }]}>
      <Image source={{ uri: imageUrl(snapshot.image_url) }} style={{ position: 'absolute', width: iw, height: ih, left, top }} accessibilityLabel={alt} />
    </View>
  )
}

const s = StyleSheet.create({
  frame: { width: '100%', overflow: 'hidden', borderRadius: P.radius, backgroundColor: '#111' },
  dim: { position: 'absolute', backgroundColor: DIM },
  box: { position: 'absolute', borderWidth: 2, borderColor: '#ffffff', borderRadius: 6, shadowColor: '#000', shadowOpacity: 0.35, shadowRadius: 1, shadowOffset: { width: 0, height: 0 } },
  thumb: { overflow: 'hidden', borderRadius: P.radius, backgroundColor: '#eee' },
})
