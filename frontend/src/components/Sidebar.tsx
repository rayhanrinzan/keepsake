import { List, Settings } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import type { ReactNode } from 'react'

export type View = 'list' | 'settings'

// Uneven blobs of colour like the logo: a dark patch top right, a dark patch bottom left, a pale glow underneath.
const blobs = (pale: string, mid: string, dark: string) =>
  `radial-gradient(45% 80% at 82% 15%, ${dark}, transparent 75%), radial-gradient(40% 90% at 12% 90%, ${dark}, transparent 75%), radial-gradient(70% 70% at 55% 110%, ${pale}, transparent 80%), ${mid}`

const TABS: { key: View; label: string; icon: LucideIcon; bg: string }[] = [
  { key: 'list', label: 'Items', icon: List, bg: blobs('#a8dcff', '#5a9ff5', '#2f6fe0') },
  { key: 'settings', label: 'Settings', icon: Settings, bg: blobs('#f0d6f6', '#a9aaf2', '#7c7ce6') },
]

/** White sidebar on a laptop, bottom tab bar on a phone. */
export function Sidebar({ view, onView, status }: {
  view: View
  onView: (v: View) => void
  status: ReactNode
}) {
  return (
    <nav className="sidebar">
      <img src="/logo.png" alt="Keepsake" className="hidden h-9 w-auto self-center md:block" />
      <div className="grid flex-1 grid-cols-2 gap-2 md:mt-8 md:flex md:flex-none md:flex-col md:gap-2.5">
        {TABS.map(({ key, label, icon: Icon, bg }) => (
          <button
            key={key}
            onClick={() => onView(key)}
            aria-current={view === key ? 'page' : undefined}
            className={`nav-tile press ${view === key ? 'on' : ''}`}
            style={{ background: bg }}
          >
            <Icon className="nav-glyph" strokeWidth={1.75} />
            <span className="nav-label">{label}</span>
          </button>
        ))}
      </div>
      <div className="mt-auto hidden md:block">{status}</div>
    </nav>
  )
}
