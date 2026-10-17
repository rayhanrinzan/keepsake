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
    snapshot: at ? {
      id: id.length, object_id: id, event_type: 'moved', timestamp: ago(at[3]), region: at[2],
      bbox: [at[0] - 0.06, at[1] - 0.06, at[0] + 0.06, at[1] + 0.06], confidence: 0.9, view_id: 'sample',
      image_url: `/api/sample-photo/${encodeURIComponent(name)}`,
    } : null,
    ...extra,
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
        // A labeled placeholder where the camera's photo would be.
        if (path.startsWith('/sample-photo/')) {
          const name = decodeURIComponent(path.slice('/sample-photo/'.length))
          res.setHeader('Content-Type', 'image/svg+xml')
          res.end(`<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360"><defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#dbeeff"/><stop offset="1" stop-color="#8fbff5"/></linearGradient></defs><rect width="640" height="360" fill="url(#g)"/><text x="320" y="170" font-family="sans-serif" font-size="28" fill="#2f6fe0" text-anchor="middle">${name}</text><text x="320" y="205" font-family="sans-serif" font-size="16" fill="#2f6fe0" opacity="0.7" text-anchor="middle">sample photo</text></svg>`)
          return
        }
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
