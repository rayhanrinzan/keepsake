import { useCallback, useEffect, useRef, useState } from 'react'
import { ChevronDown, ScanLine, Settings } from 'lucide-react'
import { api } from './lib/api'
import { setVoiceConfig, speechOutputSupported, unlockSpeech } from './lib/voice'
import type { Health, MoveEvent, QueryResult, Region, TrackedObject } from './lib/api'
import { ObjectList } from './components/ObjectList'
import { ObjectDetail } from './components/ObjectDetail'
import { PinLegend, RoomBlueprint } from './components/RoomBlueprint'
import { PaperSheet } from './components/PaperSheet'
import { ItemPanel } from './components/ItemPanel'
import { Sidebar } from './components/Sidebar'
import type { View } from './components/Sidebar'
import { SearchPanel } from './components/SearchPanel'
import { CameraPanel } from './components/CameraPanel'
import { ActivityFeed } from './components/ActivityFeed'
import { PrivacyPanel } from './components/PrivacyPanel'
import { ScanFlow } from './components/ScanFlow'
import { SettingsDialog } from './components/SettingsDialog'
import { useCameraTrace } from './lib/trace'

const POLL_MS = 1500

function readView(): View {
  try {
    const v = localStorage.getItem('keepsake.view')
    return v === 'list' || v === 'settings' ? v : 'map'
  } catch {
    return 'map'
  }
}

function CameraStatus({ health, offline }: { health: Health | null; offline: boolean }) {
  const paused = health && health.mode !== 'MONITORING'
  const [label, dot] = offline
    ? ['Offline', 'bg-danger']
    : !health ? ['Connecting…', 'bg-faint']
      : paused ? ['Paused for scan', 'bg-caution']
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
  const [regions, setRegions] = useState<Region[]>([])
  const [objects, setObjects] = useState<TrackedObject[]>([])
  const [events, setEvents] = useState<MoveEvent[]>([])
  const [view, setView] = useState<View>(readView)
  const [openId, setOpenId] = useState<string | null>(null)
  const [highlightId, setHighlightId] = useState<string | null>(null)
  const [hoverId, setHoverId] = useState<string | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [itemsOpen, setItemsOpen] = useState(() => window.innerWidth >= 768)
  const [scanning, setScanning] = useState(false)
  const [now, setNow] = useState(Date.now())
  const [prompt, setPrompt] = useState<{ id: number; text: string } | null>(null)
  const leftCount = useRef<number | null>(null) // departures already handled
  const [voiceReady, setVoiceReady] = useState(!speechOutputSupported)
  const [settingsOpen, setSettingsOpen] = useState(false)

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
      // Someone just walked out of view: offer help. The first poll only sets the baseline.
      const left = h.person_left_count ?? 0
      if (leftCount.current !== null && left > leftCount.current) {
        setPrompt({ id: left, text: 'Are you looking for something?' })
        setView('list') // the voice prompt lives in the search panel
      }
      leftCount.current = left
      setObjects(o)
      setEvents(e)
      setOffline(false)
      if (h.mode !== 'MONITORING') setScanning(true)
    } catch {
      setOffline(true)
    }
    setNow(Date.now())
  }, [])

  useEffect(() => {
    api.regions().then(setRegions).catch(() => setOffline(true))
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

  useEffect(() => {
    if (!highlightId) return
    const t = setTimeout(() => setHighlightId(null), 8000)
    return () => clearTimeout(t)
  }, [highlightId])

  /** A pin was clicked: light up its row in the items list. */
  function pickPin(id: string) {
    setSelectedId(id)
    setItemsOpen(true)
    requestAnimationFrame(() => document.getElementById(`item-${id}`)?.scrollIntoView({ behavior: 'smooth', block: 'nearest' }))
  }

  function onAnswer(r: QueryResult) {
    if (!r.object) return
    setHighlightId(r.object.object_id)
    setOpenId(r.object.object_id)
  }

  async function startScan() {
    try {
      await api.reposition('start')
      setScanning(true)
      refresh()
    } catch (e) {
      alert(e instanceof Error ? e.message : 'Could not start the scan')
    }
  }

  const closeScan = useCallback(() => {
    setScanning(false)
    api.regions().then(setRegions).catch(() => undefined)
  }, [])

  const trace = useCameraTrace(view === 'map' && health?.camera === 'active')
  const open = objects.find((o) => o.object_id === openId)
  const seenCount = objects.filter((o) => o.seen).length
  const canScan = health != null && health.camera !== 'disabled' && health.mode === 'MONITORING'
  const voiceBanner = !voiceReady && (
    <button
      onClick={() => setVoiceReady(unlockSpeech())}
      className="w-full rounded-xl bg-sunken px-4 py-3 text-left text-[14px] text-muted hover:text-ink"
    >
      Click anywhere to turn on voice prompts, like “Are you looking for something?” when you leave the room.
    </button>
  )

  return (
    <div className="md:pl-60">
      <Sidebar
        view={view}
        onView={setView}
        status={<CameraStatus health={health} offline={offline} />}
      />

      {view === 'map' && (
        <main className="h-[calc(100svh-4.5rem)] p-3 sm:p-5 md:h-svh md:p-6">
          <PaperSheet>
            {/* The drawing starts to the right of the panel, so they don't overlap until you pan or zoom. */}
            <div className="sheet-drawing">
              <RoomBlueprint
                regions={regions}
                objects={objects}
                highlightId={hoverId ?? selectedId ?? highlightId}
                peekId={selectedId}
                onSelect={pickPin}
                onOpen={setOpenId}
                trace={trace}
              />
            </div>

            {/* Title, items and legend sit on the sheet; the drawing can pass behind them. */}
            <aside className="sheet-panel">
              <div className="space-y-2 px-4 pt-4 pb-2">
                <p className="text-[13px] text-muted">{seenCount} of {objects.length} remembered</p>
                <h1 className="text-3xl leading-none font-semibold">Your room</h1>
                {health?.sample && <p className="text-[13px] text-muted">Sample data for design work.</p>}
                {offline && <p className="text-[13px] text-muted">Can&apos;t reach Keepsake. Start the backend to see updates.</p>}
                {voiceBanner}
                {health?.camera_mode === 'wearable' ? (
                  <p className="text-[13px] text-muted">
                    Worn camera: items aren&apos;t pinned on the map, because where you were looking isn&apos;t where
                    they are. Each item shows its last photo and time instead.
                  </p>
                ) : regions.length === 0 && (
                  <p className="text-[13px] text-muted">No furniture yet. Scan the room so the map can draw it.</p>
                )}
              </div>
              <button
                onClick={() => setItemsOpen((v) => !v)}
                aria-expanded={itemsOpen}
                className="flex items-center justify-between px-4 pt-2 pb-1.5 text-[15px] font-semibold"
              >
                Items <span className="flex items-center gap-1 text-[13px] font-normal text-muted">{objects.length}
                  <ChevronDown className={`size-4 transition-[rotate] duration-200 ${itemsOpen ? 'rotate-180' : ''}`} />
                </span>
              </button>
              {itemsOpen && (
                <div className="no-scrollbar min-h-0 flex-1 overflow-y-auto px-2 pb-2">
                  <ItemPanel
                    objects={objects}
                    activeId={hoverId ?? selectedId ?? highlightId}
                    onHover={setHoverId}
                    onPick={(id) => setSelectedId((cur) => (cur === id ? null : id))}
                  />
                </div>
              )}
            </aside>

            {/* Pin colours, in one row across the top right of the sheet. */}
            <div className="sheet-legend">
              <PinLegend />
            </div>
          </PaperSheet>
        </main>
      )}

      <div className={`mx-auto max-w-6xl px-4 pt-5 pb-28 sm:px-8 sm:pt-8 md:pb-12 ${view === 'map' ? 'hidden' : ''}`}>
        {health?.sample && (
          <p className="mb-4 rounded-xl bg-sunken px-4 py-3 text-[14px] text-muted">
            Sample data for design work. Run <code>npm run dev</code> with the backend for the real room.
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
            <SearchPanel onResult={onAnswer} prompt={prompt} objects={objects} />
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
                  <button onClick={startScan} disabled={!canScan} className="press button-primary self-start">
                    <ScanLine className="size-4" strokeWidth={1.75} /> Scan room
                  </button>
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
      {scanning && health && health.mode !== 'MONITORING' && (
        <ScanFlow health={health} regions={regions} onSaved={setRegions} onClose={closeScan} />
      )}
    </div>
  )
}
