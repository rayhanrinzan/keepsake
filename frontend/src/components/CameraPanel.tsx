import { useState } from 'react'
import { CameraOff } from 'lucide-react'
import { api } from '../lib/api'
import type { Health } from '../lib/api'

export function LiveFeed({ health, className = '' }: { health: Health | null; className?: string }) {
  const [streamKey, setStreamKey] = useState(0)
  const active = health?.camera === 'active'
  return (
    <div className={`relative overflow-hidden bg-ink ${className}`}>
      {active ? (
        <img
          key={streamKey}
          src={`${api.cameraUrl}?k=${streamKey}`}
          onError={() => setTimeout(() => setStreamKey((k) => k + 1), 2000)}
          alt="Live camera view with detected items outlined"
          className="size-full object-contain outline-1 -outline-offset-1 outline-white/10"
        />
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
        </p>
      )}
    </section>
  )
}
