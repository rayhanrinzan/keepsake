import { useCallback, useEffect, useRef, useState } from 'react'
import { Settings } from 'lucide-react'
import { api } from './lib/api'
import { setVoiceConfig, speechOutputSupported, startWakeListener, stopWakeListener, unlockSpeech } from './lib/voice'
import type { WakeState } from './lib/voice'
import type { ActivityEvent, Health, QueryResult, TrackedObject } from './lib/api'
import { ObjectList } from './components/ObjectList'
import { ObjectDetail } from './components/ObjectDetail'
import { Sidebar } from './components/Sidebar'
import type { View } from './components/Sidebar'
import { SearchPanel } from './components/SearchPanel'
import { CameraPanel } from './components/CameraPanel'
import { ActivityFeed } from './components/ActivityFeed'
import { PrivacyPanel } from './components/PrivacyPanel'
import { SettingsDialog } from './components/SettingsDialog'

const POLL_MS = 1500
const LOST_ASK_MS = 10_000 // an item out of view this long gets "Are you looking for something?"

function readView(): View {
  try {
    const v = localStorage.getItem('keepsake.view')
    return v === 'settings' ? v : 'list'
  } catch {
    return 'list'
  }
}

function readWakeOn(): boolean {
  try {
    return localStorage.getItem('keepsake.handsfree') !== 'off'
  } catch {
    return true
  }
}

function CameraStatus({ health, offline }: { health: Health | null; offline: boolean }) {
  const [label, dot] = offline
    ? ['Offline', 'bg-danger']
    : !health ? ['Connecting…', 'bg-faint']
      : health.camera === 'active' && health.warning ? ['Camera paused', 'bg-caution']
        : health.camera === 'active' ? ['Watching', 'bg-live']
          : health.camera === 'disabled' ? ['Camera off', 'bg-faint']
            : ['Camera unavailable', 'bg-caution']
  return (
    <span role="status" className="flex items-center gap-2 text-[13px] text-muted">
      <span aria-hidden className={`size-2 rounded-full ${dot}`} />
      {label}
    </span>
  )
}

export default function App() {
  const [health, setHealth] = useState<Health | null>(null)
  const [offline, setOffline] = useState(false)
  const [objects, setObjects] = useState<TrackedObject[]>([])
  const [events, setEvents] = useState<ActivityEvent[]>([])
  const [view, setView] = useState<View>(readView)
  const [openId, setOpenId] = useState<string | null>(null)
  const [highlightId, setHighlightId] = useState<string | null>(null)
  const [now, setNow] = useState(Date.now())
  const [wake, setWake] = useState<{ id: number; text: string } | null>(null)
  const [wakeOn, setWakeOn] = useState(readWakeOn)
  const [wakeState, setWakeState] = useState<WakeState>('off')
  const [voiceReady, setVoiceReady] = useState(!speechOutputSupported)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [prompt, setPrompt] = useState<{ id: number; text: string } | null>(null)
  const goneSince = useRef<Record<string, number>>({}) // item -> when it left the view (ms)
  const asked = useRef<Set<string>>(new Set()) // items already asked about since they left

  useEffect(() => {
    // The first click or key press anywhere lets the app speak on its own afterwards.
    const unlock = () => setVoiceReady(unlockSpeech())
    window.addEventListener('pointerdown', unlock, { once: true })
    window.addEventListener('keydown', unlock, { once: true })
    return () => {
      window.removeEventListener('pointerdown', unlock)
      window.removeEventListener('keydown', unlock)
    }
  }, [])

  const refresh = useCallback(async () => {
    try {
      const [h, o, e] = await Promise.all([api.health(), api.objects(), api.events(10)])
      setHealth(h)
      // An item that was in view and has stayed out of view for LOST_ASK_MS: ask out loud once.
      // Only items seen in view during this session count, and seeing one again re-arms it.
      const t = Date.now()
      let due = false
      for (const item of o) {
        if (item.visible) {
          goneSince.current[item.object_id] = 0
          asked.current.delete(item.object_id)
        } else if (goneSince.current[item.object_id] === 0) {
          goneSince.current[item.object_id] = t
        } else if (goneSince.current[item.object_id] && t - goneSince.current[item.object_id] >= LOST_ASK_MS
                   && !asked.current.has(item.object_id)) {
          asked.current.add(item.object_id)
          due = true
        }
      }
      if (due) {
        setPrompt({ id: t, text: 'Are you looking for something?' })
        setView('list') // the voice conversation lives in the search panel
      }
      setObjects(o)
      setEvents(e)
      setOffline(false)
    } catch {
      setOffline(true)
    }
    setNow(Date.now())
  }, [])

  useEffect(() => {
    api.voice().then((v) => setVoiceConfig({ provider: v.provider, voice_id: v.voice_id, speed: v.speed })).catch(() => undefined)
    refresh()
    const id = setInterval(refresh, POLL_MS)
    return () => clearInterval(id)
  }, [refresh])

  useEffect(() => {
    try {
      localStorage.setItem('keepsake.view', view)
    } catch {
      /* storage unavailable */
    }
  }, [view])

  // Hands-free: "where are my keys" (or "hey Keepsake") starts a lookup, like a smart speaker.
  // Starts after the first click, because browsers need one before the mic and speech work.
  const onWakeHeard = useCallback((said: string) => {
    setWake({ id: Date.now(), text: said })
    setView('list') // the conversation lives in the search panel
  }, [])

  useEffect(() => {
    if (!wakeOn || !voiceReady) return
    startWakeListener(onWakeHeard, setWakeState)
    return () => stopWakeListener()
  }, [wakeOn, voiceReady, onWakeHeard])

  function toggleWake() {
    if (wakeOn && wakeState === 'blocked') {
      // Try again, e.g. after the user allowed the microphone.
      stopWakeListener()
      startWakeListener(onWakeHeard, setWakeState)
      return
    }
    const next = !wakeOn
    setWakeOn(next)
    try {
      localStorage.setItem('keepsake.handsfree', next ? 'on' : 'off')
    } catch {
      /* storage unavailable */
    }
  }

  useEffect(() => {
    if (!highlightId) return
    const t = setTimeout(() => setHighlightId(null), 8000)
    return () => clearTimeout(t)
  }, [highlightId])

  function onAnswer(r: QueryResult) {
    if (!r.object) return
    setHighlightId(r.object.object_id)
    setOpenId(r.object.object_id)
  }

  const open = objects.find((o) => o.object_id === openId)
  const seenCount = objects.filter((o) => o.seen).length
  const voiceBanner = !voiceReady && (
    <button
      onClick={() => setVoiceReady(unlockSpeech())}
      className="w-full rounded-xl bg-sunken px-4 py-3 text-left text-[14px] text-muted hover:text-ink"
    >
      Click anywhere to turn on voice. Then just say “Where are my keys?”
    </button>
  )

  return (
    <div className="md:pl-60">
      <Sidebar
        view={view}
        onView={setView}
        status={<CameraStatus health={health} offline={offline} />}
      />

      <div className="mx-auto max-w-6xl px-4 pt-5 pb-28 sm:px-8 sm:pt-8 md:pb-12">
        {health?.sample && (
          <p className="mb-4 rounded-xl bg-sunken px-4 py-3 text-[14px] text-muted">
            Sample data for design work. Run <code>npm run dev</code> with the backend for real memories.
          </p>
        )}
        {voiceBanner && <div className="mb-4">{voiceBanner}</div>}
        {offline && (
          <p className="mb-4 rounded-xl bg-sunken px-4 py-3 text-[14px] text-muted">
            Can&apos;t reach Keepsake. Showing the last memories loaded. Start the backend to see updates.
          </p>
        )}

        {view === 'list' && (
          <main className="space-y-5">
            <div className="space-y-2">
              <p className="text-[13px] text-muted">{seenCount} of {objects.length} remembered</p>
              <h1 className="text-3xl leading-none font-semibold">Your items</h1>
            </div>
            <SearchPanel
              onResult={onAnswer}
              prompt={prompt}
              objects={objects}
              wake={wake}
              onWakeHandled={() => setWake(null)}
              wakeState={wakeOn ? wakeState : 'off'}
              onToggleWake={toggleWake}
            />
            <CameraPanel health={health} />
            <ObjectList objects={objects} now={now} highlightId={highlightId} onOpen={setOpenId} />
            <ActivityFeed events={events} />
          </main>
        )}

        {view === 'settings' && (
          <main className="space-y-5">
            <h1 className="text-3xl leading-none font-semibold">Settings</h1>
            <div className="grid gap-5 lg:grid-cols-2">
              <CameraPanel health={health} />
              <div className="space-y-5">
                <PrivacyPanel health={health} onChanged={refresh} />
                <div className="flex flex-wrap gap-3">
                  <button
                    onClick={() => setSettingsOpen(true)}
                    className="press flex h-10 items-center gap-2 rounded-xl bg-surface px-3.5 text-[14px] font-medium shadow-ring hover:bg-sunken"
                  >
                    <Settings className="size-4" strokeWidth={1.75} /> Customize voice
                  </button>
                </div>
              </div>
            </div>
          </main>
        )}
      </div>

      {settingsOpen && <SettingsDialog onClose={() => setSettingsOpen(false)} />}
      {open && <ObjectDetail key={open.object_id} o={open} now={now} onClose={() => setOpenId(null)} />}
    </div>
  )
}
