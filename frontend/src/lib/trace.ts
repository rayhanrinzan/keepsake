import { useEffect, useState } from 'react'
import { api } from './api'

export interface Trace {
  url: string
  /** Width / height of the camera frame. */
  aspect: number
}

const WIDTH = 480
const REFRESH_MS = 2500

/**
 * Turns a camera frame into a blueprint-style line drawing: grayscale, a light blur,
 * then Sobel edges drawn in the logo blue on a transparent background.
 */
function trace(img: ImageBitmap): Trace {
  const w = WIDTH
  const h = Math.round((img.height / img.width) * w)
  const canvas = document.createElement('canvas')
  canvas.width = w
  canvas.height = h
  const ctx = canvas.getContext('2d', { willReadFrequently: true })!
  ctx.filter = 'grayscale(1) blur(1px)'
  ctx.drawImage(img, 0, 0, w, h)
  const src = ctx.getImageData(0, 0, w, h).data
  const out = ctx.createImageData(w, h)
  const g = (x: number, y: number) => src[(y * w + x) * 4]
  for (let y = 1; y < h - 1; y++) {
    for (let x = 1; x < w - 1; x++) {
      const gx = g(x + 1, y - 1) + 2 * g(x + 1, y) + g(x + 1, y + 1) - g(x - 1, y - 1) - 2 * g(x - 1, y) - g(x - 1, y + 1)
      const gy = g(x - 1, y + 1) + 2 * g(x, y + 1) + g(x + 1, y + 1) - g(x - 1, y - 1) - 2 * g(x, y - 1) - g(x + 1, y - 1)
      const mag = Math.hypot(gx, gy)
      if (mag < 70) continue
      const i = (y * w + x) * 4
      out.data[i] = 47
      out.data[i + 1] = 111
      out.data[i + 2] = 224
      out.data[i + 3] = Math.min(220, (mag - 70) * 1.4 + 60)
    }
  }
  ctx.filter = 'none'
  ctx.clearRect(0, 0, w, h)
  ctx.putImageData(out, 0, 0)
  return { url: canvas.toDataURL('image/png'), aspect: w / h }
}

/** A line drawing of what the camera sees right now, refreshed every few seconds while the camera is on. */
export function useCameraTrace(enabled: boolean): Trace | null {
  const [result, setResult] = useState<Trace | null>(null)
  useEffect(() => {
    if (!enabled) return
    let stopped = false
    async function update() {
      if (document.hidden) return
      try {
        const res = await fetch(`${api.cameraUrl}/frame`, { cache: 'no-store' })
        if (!res.ok) return
        const img = await createImageBitmap(await res.blob())
        if (!stopped) setResult(trace(img))
        img.close()
      } catch {
        /* the next refresh retries */
      }
    }
    update()
    const id = setInterval(update, REFRESH_MS)
    return () => {
      stopped = true
      clearInterval(id)
    }
  }, [enabled])
  return enabled ? result : null
}
