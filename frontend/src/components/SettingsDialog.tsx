import { useEffect, useRef, useState } from 'react'
import { LoaderCircle, Play, X } from 'lucide-react'
import { api } from '../lib/api'
import type { VoiceConfig, VoiceInfo } from '../lib/api'
import { setVoiceConfig, speak, stopVoice } from '../lib/voice'

const SAMPLE = 'Hi, I’m Keepsake. I last saw your keys on the desk a few minutes ago.'

export function SettingsDialog({ onClose }: { onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null)
  const [info, setInfo] = useState<VoiceInfo | null>(null)
  const [draft, setDraft] = useState<VoiceConfig | null>(null)
  const [previewing, setPreviewing] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    dialog.current?.showModal()
    api.voice()
      .then((v) => {
        setInfo(v)
        setDraft({ provider: v.provider, voice_id: v.voice_id, speed: v.speed })
      })
      .catch((e) => setError(e.message))
    return () => stopVoice()
  }, [])

  const update = (patch: Partial<VoiceConfig>) => setDraft((d) => (d ? { ...d, ...patch } : d))

  async function preview() {
    if (!draft) return
    setError(null)
    setPreviewing(true)
    try {
      await speak(SAMPLE, { ...draft, strict: true })
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Preview failed')
    }
    setPreviewing(false)
  }

  async function save() {
    if (!draft) return
    setSaving(true)
    setError(null)
    try {
      const v = await api.setVoice(draft)
      setVoiceConfig({ provider: v.provider, voice_id: v.voice_id, speed: v.speed })
      dialog.current?.close()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not save')
    }
    setSaving(false)
  }

  const grok = draft?.provider === 'grok'

  return (
    <dialog
      ref={dialog}
      onClose={onClose}
      onClick={(e) => e.target === dialog.current && dialog.current?.close()}
      aria-labelledby="settings-title"
      className="enter m-auto max-h-[92dvh] w-[min(560px,calc(100vw-24px))] overflow-y-auto overscroll-contain rounded-[20px] border border-transparent bg-surface p-0 text-ink shadow-overlay backdrop:bg-black/30"
    >
      <div className="flex items-center justify-between gap-4 px-6 pt-5 pb-2">
        <h2 id="settings-title" className="text-lg font-semibold">Settings</h2>
        <button
          onClick={() => dialog.current?.close()}
          className="press -mr-2 flex size-10 items-center justify-center rounded-lg text-muted hover:bg-sunken hover:text-ink"
          aria-label="Close"
        >
          <X className="size-5" strokeWidth={1.75} />
        </button>
      </div>

      <section className="px-6 pb-6">
        <h3 className="font-semibold">Customize voice</h3>
        <p className="mt-1 text-[14px] text-muted">How Keepsake sounds when it answers or asks if you’re looking for something.</p>

        {!draft || !info ? (
          <p className="mt-4 flex items-center gap-2 text-[14px] text-muted">
            {error ?? <><LoaderCircle className="size-4 animate-spin motion-reduce:animate-none" strokeWidth={1.75} /> Loading…</>}
          </p>
        ) : (
          <>
            <div role="radiogroup" aria-label="Voice engine" className="mt-4 inline-flex rounded-xl bg-sunken p-1">
              {([['grok', 'Grok voice'], ['browser', 'Browser voice']] as const).map(([key, label]) => (
                <button
                  key={key}
                  role="radio"
                  aria-checked={draft.provider === key}
                  disabled={key === 'grok' && !info.grok_available}
                  onClick={() => update({ provider: key })}
                  className={`h-8 rounded-lg border border-transparent px-4 text-[14px] font-medium transition-[background-color,color] duration-150 disabled:opacity-40 ${draft.provider === key ? 'bg-surface text-ink shadow-ring' : 'text-muted hover:text-ink'}`}
                >
                  {label}
                </button>
              ))}
            </div>
            {!info.grok_available && (
              <p className="mt-2 text-[13px] text-muted">
                To use Grok voices, add <code>XAI_API_KEY=xai-…</code> (from console.x.ai) to <code>.env</code> and restart the backend.
              </p>
            )}

            {grok && (
              <fieldset className="mt-5">
                <legend className="text-[13px] text-muted">Voice</legend>
                <div className="mt-2 grid grid-cols-3 gap-2 sm:grid-cols-4">
                  {info.voices.map((v) => (
                    <button
                      key={v.voice_id}
                      role="radio"
                      aria-checked={draft.voice_id === v.voice_id}
                      onClick={() => update({ voice_id: v.voice_id })}
                      className={`press h-10 rounded-xl border px-3 text-[14px] font-medium ${draft.voice_id === v.voice_id ? 'border-ink bg-ink text-white' : 'border-hairline bg-canvas hover:bg-sunken'}`}
                    >
                      {v.name}
                    </button>
                  ))}
                </div>
              </fieldset>
            )}

            <label className="mt-5 block">
              <span className="flex justify-between text-[13px] text-muted">
                <span>Speed</span>
                <span className="tabular-nums">{draft.speed.toFixed(2)}×</span>
              </span>
              <input
                type="range"
                min={0.7}
                max={1.5}
                step={0.05}
                value={draft.speed}
                onChange={(e) => update({ speed: Number(e.target.value) })}
                className="mt-2 w-full accent-ink"
              />
            </label>

            {error && <p className="mt-3 text-[13px] text-danger">{error}</p>}

            <div className="mt-6 flex justify-between gap-3">
              <button
                onClick={preview}
                disabled={previewing}
                className="press flex h-10 items-center gap-2 rounded-xl border border-transparent bg-surface px-3.5 text-[14px] font-medium shadow-ring hover:bg-sunken disabled:opacity-50"
              >
                {previewing
                  ? <LoaderCircle className="size-4 animate-spin motion-reduce:animate-none" strokeWidth={1.75} />
                  : <Play className="size-4" strokeWidth={1.75} />}
                Preview
              </button>
              <button
                onClick={save}
                disabled={saving}
                className="press h-10 rounded-xl bg-ink px-5 text-[14px] font-medium text-white hover:bg-ink/85 disabled:opacity-50"
              >
                Save
              </button>
            </div>
          </>
        )}
      </section>
    </dialog>
  )
}
