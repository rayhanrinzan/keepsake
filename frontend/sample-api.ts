import type { Plugin } from 'vite'

/*
 * Design-only sample backend for `npm run dev:sample`, so the UI can be worked on
 * without the camera. It is never used by `npm run dev` or the production build,
 * and the app shows a "Sample data" banner while it's on.
 */

function objects() {
  const ago = (min: number) => new Date(Date.now() - min * 60_000).toISOString()
  // Minutes since last seen, or null if never seen. Photos have a time, never a room location.
  const item = (id: string, name: string, icon: string, minutes: number | null, visible = false) => ({
    object_id: `${id.replace(/ /g, '_')}_01`, category: id, name, icon,
    seen: minutes != null, status: minutes == null ? 'never' : visible ? 'visible' : 'last_seen',
    last_seen: minutes != null ? ago(minutes) : null, visible, confidence: minutes != null ? 0.9 : null,
    snapshot: minutes != null ? {
      id: name.length, object_id: id, event_type: 'object_observed', timestamp: ago(minutes),
      bbox: [0.4, 0.4, 0.6, 0.6], confidence: 0.9, image_url: `/api/sample-photo/${encodeURIComponent(name)}`,
    } : null,
  })
  return [
    item('bottle', 'Water Bottle', 'bottle', 12),
    item('car key', 'Keys', 'keys', 0, true),
    item('wallet', 'Wallet', 'wallet', 3),
    item('airpods case', 'AirPods', 'airpods', 40),
    item('glasses', 'Glasses', 'glasses', null),
    item('backpack', 'Backpack', 'backpack', 95),
  ]
}

const health = {
  status: 'ok', camera: 'disabled', error: null, warning: null, fps: 0, detections: [],
  camera_mode: 'wearable', capture_enabled: true, sample: true,
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
            : path.startsWith('/objects') && !path.includes('/snapshots') ? objects()
              : path.startsWith('/query') ? { found: false, answer: 'Search needs the real backend.', object: null }
                : []
        res.setHeader('Content-Type', 'application/json')
        res.end(JSON.stringify(body))
      })
    },
  }
}
