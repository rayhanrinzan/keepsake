import { useEffect, useState } from 'react'
import { CameraOff } from 'lucide-react'
import { api } from '../lib/api'
import type { Health } from '../lib/api'

const FRAME_MS = 200 // ~5 fps, matching detection
const STALE_MS = 3000

/**
 * Polls the newest frame as a plain image request. Unlike a long-lived MJPEG stream, a failed or
 * stalled request just gets replaced by the next one, so the view can't freeze silently.
 */
function useLiveFrames(enabled: boolean) {
  const [src, setSrc] = useState<string | null>(null)
  const [lastAt, setLastAt] = useState(0)

  useEffect(() => {
    if (!enabled) return
    let stopped = false
    let current: string | null = null
    let lastId = ''
    async function loop() {
      while (!stopped) {
        const started = performance.now()
        if (!document.hidden) {
          const ctrl = new AbortController()
          const timeout = setTimeout(() => ctrl.abort(), 2500)
          try {
            const res = await fetch(api.frameUrl, { cache: 'no-store', signal: ctrl.signal })
            const id = res.headers.get('X-Frame-Id') ?? ''
            if (res.ok && id !== lastId) {
              lastId = id
              const url = URL.createObjectURL(await res.blob())
              if (stopped) {
                URL.revokeObjectURL(url)
                break
              }
              if (current) URL.revokeObjectURL(current)
              current = url
              setSrc(url)
              setLastAt(Date.now())
            }
          } catch {
            /* network hiccup or timeout: the next iteration retries */
          } finally {
            clearTimeout(timeout)
          }
        }
        await new Promise((r) => setTimeout(r, Math.max(0, FRAME_MS - (performance.now() - started))))
      }
    }
    loop()
    return () => {
      stopped = true
      if (current) URL.revokeObjectURL(current)
    }
  }, [enabled])

  return { src, lastAt }
}

export function LiveFeed({ health, className = '' }: { health: Health | null; className?: string }) {
  const active = health?.camera === 'active'
  const { src, lastAt } = useLiveFrames(active)
  const [now, setNow] = useState(Date.now())
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(t)
  }, [])
  const stale = active && src != null && now - lastAt > STALE_MS
  return (
    <div className={`relative overflow-hidden bg-ink ${className}`}>
      {active && src ? (
        <>
          <img
            src={src}
            alt="Live camera view with detected items outlined"
            className="size-full object-contain outline-1 -outline-offset-1 outline-white/10"
          />
          {stale && (
            <p className="absolute inset-x-0 bottom-0 bg-black/60 px-3 py-1.5 text-[13px] text-white">
              Live view paused. Reconnecting…
            </p>
          )}
        </>
      ) : active ? (
        <div className="flex size-full items-center justify-center text-[13px] text-white/70">Loading camera…</div>
      ) : (
        <div className="flex size-full flex-col items-center justify-center gap-2 p-4 text-center text-[13px] text-white/70">
          <CameraOff className="size-5" strokeWidth={1.75} />
          <p>{!health ? 'Connecting…' : health.camera === 'disabled' ? 'Camera is turned off' : health.error ?? 'Starting camera…'}</p>
        </div>
      )}
    </div>
  )
}

export function CameraPanel({ health }: { health: Health | null }) {
  const active = health?.camera === 'active'
  return (
    <section className="card overflow-hidden">
      <h2 className="px-4 pt-3.5 pb-3 font-semibold">Camera</h2>
      <LiveFeed health={health} className="aspect-video" />
      {health?.warning && <p className="bg-caution-soft px-4 py-2.5 text-[13px] text-caution">{health.warning}</p>}
      {active && (
        <p className="px-4 py-3 text-[13px] text-muted">
          {health.detections.length === 0
            ? 'No tracked items in view'
            : `In view: ${health.detections.map((d) => d.name).join(', ')}`}
          {health.person_present && ' · Person in view'}
        </p>
      )}
    </section>
  )
}
