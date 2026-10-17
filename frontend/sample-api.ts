import type { Plugin } from 'vite'

/*
 * Design-only sample backend for `npm run dev:sample`, so the UI can be worked on
 * without the camera. It is never used by `npm run dev` or the production build,
 * and the app shows a "Sample data" banner while it's on.
 */

const regions = [
  { name: 'Bed', kind: 'bed', x0: 0.05, y0: 0.15, x1: 0.42, y1: 0.6 },
  { name: 'Couch', kind: 'couch', x0: 0.55, y0: 0.08, x1: 0.95, y1: 0.3 },
  { name: 'Table', kind: 'dining table', x0: 0.55, y0: 0.55, x1: 0.8, y1: 0.85 },
  { name: 'Chair', kind: 'chair', x0: 0.83, y0: 0.6, x1: 0.95, y1: 0.78 },
]

function objects() {
  const ago = (min: number) => new Date(Date.now() - min * 60_000).toISOString()
  const item = (id: string, name: string, icon: string, at: [number, number, string, number] | null, visible = false, extra = {}) => ({
    object_id: id, category: id, name, icon,
    seen: at != null, status: at == null ? 'never' : visible ? 'visible' : 'last_seen',
    region: at?.[2] ?? null, x: at?.[0] ?? null, y: at?.[1] ?? null, last_seen: at ? ago(at[3]) : null,
    visible, confidence: at ? 0.9 : null, moving: false, awaiting_reconfirmation: false, lost_while_moving: false,
    snapshot: null, ...extra,
  })
  return [
    item('cell phone', 'Phone', 'phone', [0.2, 0.35, 'Bed', 0], true),
    item('bottle', 'Water bottle', 'bottle', [0.65, 0.7, 'Table', 12]),
    item('laptop', 'Laptop', 'laptop', [0.7, 0.2, 'Couch', 0], true),
    item('cup', 'Mug', 'cup', [0.3, 0.85, 'Left side', 3], false, { moving: true }),
    item('book', 'Book', 'book', [0.75, 0.65, 'Table', 40], true),
    item('backpack', 'Backpack', 'backpack', [0.9, 0.7, 'Chair', 95]),
    item('remote', 'TV remote', 'remote', null),
    item('mouse', 'Mouse', 'mouse', null),
  ]
}

const health = {
  status: 'ok', camera: 'disabled', error: null, warning: null, fps: 0, detections: [],
  mode: 'MONITORING', reference_ready: false, proposal: [], view_id: 'sample', capture_enabled: true, sample: true,
}

export function sampleApi(): Plugin {
  return {
    name: 'keepsake-sample-api',
    configureServer(server) {
      server.middlewares.use('/api', (req, res) => {
        const path = req.url ?? ''
        const body = path.startsWith('/health') ? health
          : path.startsWith('/regions') ? regions
            : path.startsWith('/objects') && !path.includes('/snapshots') ? objects()
              : path.startsWith('/query') ? { found: false, answer: 'Search needs the real backend.', object: null }
                : []
        res.setHeader('Content-Type', 'application/json')
        res.end(JSON.stringify(body))
      })
    },
  }
}
