import { useCallback, useEffect, useState } from 'react'
import { ChevronDown, ScanLine } from 'lucide-react'
import { api } from './lib/api'
import type { Health, MoveEvent, QueryResult, Region, TrackedObject } from './lib/api'
import { ObjectList } from './components/ObjectList'
import { ObjectDetail } from './components/ObjectDetail'
import { PinLegend, RoomBlueprint } from './components/RoomBlueprint'
import { ItemPanel } from './components/ItemPanel'
import { Sidebar } from './components/Sidebar'
import type { View } from './components/Sidebar'
import { SearchPanel } from './components/SearchPanel'
import { CameraPanel } from './components/CameraPanel'
import { ActivityFeed } from './components/ActivityFeed'
import { PrivacyPanel } from './components/PrivacyPanel'
import { ScanFlow } from './components/ScanFlow'

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
    <span role="status" className="flex items-center gap-2 text-[13px] text-white/60">
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
  const [itemsOpen, setItemsOpen] = useState(() => window.innerWidth >= 768)
  const [scanning, setScanning] = useState(false)
  const [now, setNow] = useState(Date.now())

  const refresh = useCallback(async () => {
    try {
      const [h, o, e] = await Promise.all([api.health(), api.objects(), api.events(10)])
      setHealth(h)
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

  /** A pin was clicked: light up its card under the map. */
  function pickPin(id: string) {
    setHighlightId(id)
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

  const open = objects.find((o) => o.object_id === openId)
  const seenCount = objects.filter((o) => o.seen).length
  const canScan = health != null && health.camera !== 'disabled' && health.mode === 'MONITORING'

  return (
    <div className="md:pl-60">
      <Sidebar
        view={view}
        onView={setView}
        status={<CameraStatus health={health} offline={offline} />}
        canScan={canScan}
        onScan={startScan}
      />

      {view === 'map' && (
        <main className="relative h-svh overflow-hidden">
          {/* The room fills the whole window; the title and items float over it on frosted glass. */}
          <RoomBlueprint regions={regions} objects={objects} highlightId={hoverId ?? highlightId} onSelect={pickPin} />

          <div className="frost absolute top-4 left-4 flex max-h-[calc(100%-6rem)] w-[min(340px,calc(100%-2rem))] flex-col sm:top-6 sm:left-6 md:max-h-[calc(100%-3rem)]">
            <div className="space-y-2 px-5 pt-4 pb-3">
              <p className="text-[13px] text-muted tabular-nums">{seenCount} of {objects.length} remembered</p>
              <h1 className="text-3xl leading-none font-semibold">Your room</h1>
              {health?.sample && <p className="text-[13px] text-muted">Sample data for design work.</p>}
              {offline && <p className="text-[13px] text-caution">Can&apos;t reach Keepsake. Start the backend to see updates.</p>}
              {regions.length === 0 && (
                <div className="space-y-2 pt-1">
                  <p className="text-[13px] text-muted">No furniture yet. Scan the room so the map can draw it.</p>
                  <button onClick={startScan} disabled={!canScan} className="press button-primary">
                    <ScanLine className="size-4" strokeWidth={1.75} /> Scan room
                  </button>
                </div>
              )}
            </div>
            <button
              onClick={() => setItemsOpen((v) => !v)}
              aria-expanded={itemsOpen}
              className="flex items-center justify-between px-5 pt-2 pb-1.5 text-[15px] font-semibold"
            >
              Items <span className="flex items-center gap-1 text-[13px] font-normal text-muted">{objects.length}
                <ChevronDown className={`size-4 transition-[rotate] duration-200 ${itemsOpen ? 'rotate-180' : ''}`} />
              </span>
            </button>
            {itemsOpen && (
              <div className="no-scrollbar min-h-0 overflow-y-auto px-3 pb-3">
                <ItemPanel objects={objects} activeId={hoverId ?? highlightId} onHover={setHoverId} onOpen={setOpenId} />
              </div>
            )}
          </div>

          <div className="frost absolute top-4 right-4 hidden px-4 py-2.5 sm:top-6 sm:right-6 lg:block">
            <PinLegend />
          </div>
        </main>
      )}

      <div className={`mx-auto max-w-6xl px-4 pt-5 pb-28 sm:px-8 sm:pt-8 md:pb-12 ${view === 'map' ? 'hidden' : ''}`}>
        {health?.sample && (
          <p className="mb-4 rounded-xl bg-sunken px-4 py-3 text-[14px] text-muted">
            Sample data for design work. Run <code>npm run dev</code> with the backend for the real room.
          </p>
        )}
        {offline && (
          <p className="mb-4 rounded-xl bg-caution-soft px-4 py-3 text-caution">
            Can&apos;t reach Keepsake. Showing the last memories loaded. Start the backend to see updates.
          </p>
        )}

        {view === 'list' && (
          <main className="space-y-5">
            <h1 className="text-3xl font-semibold">List</h1>
            <SearchPanel onResult={onAnswer} />
            <p className="text-[13px] text-muted tabular-nums">{seenCount} of {objects.length} remembered</p>
            <ObjectList objects={objects} now={now} highlightId={highlightId} onOpen={setOpenId} />
            <ActivityFeed events={events} />
          </main>
        )}

        {view === 'settings' && (
          <main className="space-y-5">
            <h1 className="text-3xl font-semibold">Settings</h1>
            <div className="grid gap-5 lg:grid-cols-2">
              <CameraPanel health={health} />
              <div className="space-y-5">
                <PrivacyPanel health={health} onChanged={refresh} />
                <button onClick={startScan} disabled={!canScan} className="press button-primary md:hidden">
                  <ScanLine className="size-4" strokeWidth={1.75} /> Scan room
                </button>
              </div>
            </div>
          </main>
        )}
      </div>

      {open && <ObjectDetail key={open.object_id} o={open} now={now} onClose={() => setOpenId(null)} />}
      {scanning && health && health.mode !== 'MONITORING' && (
        <ScanFlow health={health} regions={regions} onSaved={setRegions} onClose={closeScan} />
      )}
    </div>
  )
}
