import { useState } from 'react'
import { api } from '../lib/api'
import type { Health } from '../lib/api'

export function PrivacyPanel({ health, onChanged }: { health: Health | null; onChanged: () => void }) {
  const [error, setError] = useState<string | null>(null)
  const capture = health?.capture_enabled ?? true

  async function toggle() {
    setError(null)
    await api.setCapture(!capture).catch((e) => setError(e.message))
    onChanged()
  }

  async function clearAll() {
    if (!confirm('Forget every remembered location and delete all saved photos? This can’t be undone.')) return
    setError(null)
    await api.clear().catch((e) => setError(e.message))
    onChanged()
  }

  return (
    <section className="card px-4 py-3.5">
      <h2 className="font-semibold">Privacy</h2>
      <p className="mt-1 text-[14px] text-muted">
        Video is processed on this computer. Keepsake saves selected item photos, not a recording, and never uploads them.
      </p>
      <div className="mt-3 flex min-h-11 items-center justify-between gap-3 border-t border-hairline pt-3">
        <span id="capture-label" className="text-[14px] font-medium">Save item photos</span>
        <button
          role="switch"
          aria-checked={capture}
          aria-labelledby="capture-label"
          onClick={toggle}
          disabled={!health}
          className={`relative h-6 w-10 shrink-0 rounded-full border border-transparent transition-[background-color] duration-150 ${capture ? 'bg-deep' : 'bg-hairline'}`}
        >
          <span className={`absolute top-0.5 left-0.5 size-[18px] rounded-full bg-white shadow-ring transition-[translate] duration-150 motion-reduce:transition-none ${capture ? 'translate-x-4' : ''}`} />
        </button>
      </div>
      {!capture && <p className="text-[13px] text-caution">Photo saving is paused. Locations still update.</p>}
      <button onClick={clearAll} className="press mt-2 min-h-9 rounded-lg px-2 -ml-2 text-[14px] font-medium text-danger hover:bg-sunken">
        Clear all memories and photos
      </button>
      {error && <p className="mt-1 text-[13px] text-danger">{error}</p>}
    </section>
  )
}
