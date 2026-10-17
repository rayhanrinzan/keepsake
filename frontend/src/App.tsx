import { useCallback, useEffect, useRef, useState } from 'react'
import { ScanLine } from 'lucide-react'
import { api } from './lib/api'
import type { Health, MoveEvent, QueryResult, Region, TrackedObject } from './lib/api'
import { ObjectList } from './components/ObjectList'
import { ObjectDetail } from './components/ObjectDetail'
import { RoomMap } from './components/RoomMap'
import { SearchPanel } from './components/SearchPanel'
import { CameraPanel } from './components/CameraPanel'
import { ActivityFeed } from './components/ActivityFeed'
import { PrivacyPanel } from './components/PrivacyPanel'
import { ScanFlow } from './components/ScanFlow'

const POLL_MS = 1500
type View = 'list' | 'map'

function readView(): View {
  try {
    return localStorage.getItem('keepsake.view') === 'map' ? 'map' : 'list'
  } catch {
    return 'list'
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
  const [scanning, setScanning] = useState(false)
  const [now, setNow] = useState(Date.now())
  const [prompt, setPrompt] = useState<{ id: number; text: string } | null>(null)
  const leftCount = useRef<number | null>(null) // departures already handled

  const refresh = useCallback(async () => {
    try {
      const [h, o, e] = await Promise.all([api.health(), api.objects(), api.events(10)])
      setHealth(h)
      // Someone just walked out of view: offer help. The first poll only sets the baseline.
      const left = h.person_left_count ?? 0
      if (leftCount.current !== null && left > leftCount.current) {
        setPrompt({ id: left, text: 'Are you looking for something?' })
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
    <div className="mx-auto max-w-6xl px-4 pt-5 pb-16 sm:px-6 sm:pt-8">
      <header className="mb-6 flex items-center justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Keepsake</h1>
          <p className="text-[14px] text-muted">Your room remembers, so you don&apos;t have to.</p>
        </div>
        <div className="flex items-center gap-4">
          <CameraStatus health={health} offline={offline} />
          <button
            onClick={startScan}
            disabled={!canScan}
            className="press flex h-10 items-center gap-2 rounded-xl border border-transparent bg-surface px-3.5 text-[14px] font-medium shadow-ring hover:bg-sunken disabled:opacity-50"
          >
            <ScanLine className="size-4" strokeWidth={1.75} /> Scan room
          </button>
        </div>
      </header>

      {offline && (
        <p className="mb-4 rounded-xl bg-caution-soft px-4 py-3 text-caution">
          Can&apos;t reach Keepsake. Showing the last memories loaded. Start the backend to see updates.
        </p>
      )}

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_320px]">
        <main className="min-w-0 space-y-5">
          <SearchPanel onResult={onAnswer} prompt={prompt} />

          <div className="flex items-center justify-between gap-3">
            {/* Segmented control: inner radius 8 + padding 4 = outer 12 */}
            <div role="tablist" aria-label="View" className="inline-flex rounded-xl bg-sunken p-1">
              {(['list', 'map'] as const).map((key) => (
                <button
                  key={key}
                  role="tab"
                  aria-selected={view === key}
                  onClick={() => setView(key)}
                  className={`h-8 rounded-lg border border-transparent px-4 text-[14px] font-medium transition-[background-color,color] duration-150 ${view === key ? 'bg-surface text-ink shadow-ring' : 'text-muted hover:text-ink'}`}
                >
                  {key === 'list' ? 'List' : 'Map'}
                </button>
              ))}
            </div>
            <span className="text-[13px] text-muted tabular-nums">{seenCount} of {objects.length} remembered</span>
          </div>

          {view === 'list' ? (
            <ObjectList objects={objects} now={now} highlightId={highlightId} onOpen={setOpenId} />
          ) : (
            <RoomMap
              regions={regions}
              objects={objects}
              highlightId={highlightId}
              onOpen={setOpenId}
              onScan={startScan}
              referenceUrl={health?.reference_ready ? `${api.referenceUrl}?v=${health.view_id}` : null}
            />
          )}
        </main>

        <aside className="space-y-4">
          <CameraPanel health={health} />
          <ActivityFeed events={events} />
          <PrivacyPanel health={health} onChanged={refresh} />
        </aside>
      </div>

      {open && <ObjectDetail key={open.object_id} o={open} now={now} onClose={() => setOpenId(null)} />}
      {scanning && health && health.mode !== 'MONITORING' && (
        <ScanFlow health={health} regions={regions} onSaved={setRegions} onClose={closeScan} />
      )}
    </div>
  )
}
