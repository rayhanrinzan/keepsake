import { List, Map, ScanLine, Settings } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import type { ReactNode } from 'react'

export type View = 'map' | 'list' | 'settings'

const TABS: { key: View; label: string; icon: LucideIcon; bg: string }[] = [
  { key: 'map', label: 'Map', icon: Map, bg: 'radial-gradient(ellipse at 50% 0%, #8fd0ff, #2f6fe0)' },
  { key: 'list', label: 'List', icon: List, bg: 'radial-gradient(ellipse at 50% 0%, #b6f0e4, #3a9fbf)' },
  { key: 'settings', label: 'Settings', icon: Settings, bg: 'radial-gradient(ellipse at 50% 0%, #e3b8f0, #7c7fe8)' },
]

/** Black sidebar on a laptop, bottom tab bar on a phone. */
export function Sidebar({ view, onView, status, canScan, onScan }: {
  view: View
  onView: (v: View) => void
  status: ReactNode
  canScan: boolean
  onScan: () => void
}) {
  return (
    <nav className="sidebar">
      <img src="/logo.png" alt="Keepsake" className="hidden h-9 w-auto self-center md:block" />
      <div className="grid flex-1 grid-cols-3 gap-2 md:mt-8 md:flex md:flex-none md:flex-col md:gap-2.5">
        {TABS.map(({ key, label, icon: Icon, bg }) => (
          <button
            key={key}
            onClick={() => onView(key)}
            aria-current={view === key ? 'page' : undefined}
            className={`nav-tile press ${view === key ? 'on' : ''}`}
            style={view === key ? { background: bg } : undefined}
          >
            <Icon className="nav-glyph" strokeWidth={1.75} />
            <span className="nav-label">{label}</span>
          </button>
        ))}
      </div>
      <div className="mt-auto hidden space-y-3 md:block">
        {status}
        <button
          onClick={onScan}
          disabled={!canScan}
          className="press flex h-10 w-full items-center justify-center gap-1.5 rounded-xl bg-white/10 text-[13px] font-medium text-white hover:bg-white/15 disabled:opacity-40"
        >
          <ScanLine className="size-4" strokeWidth={1.75} /> Scan room
        </button>
      </div>
    </nav>
  )
}
