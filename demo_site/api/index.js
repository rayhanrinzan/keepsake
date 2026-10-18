// Keepsake's recorded demo API (Vercel serverless). Same routes and shapes as the backend, answered
// from recording.json: real photos from one session, each checked by a person (scripts/export_demo.py).
// Nothing here detects or invents anything; the live camera only runs on the wearer's laptop.
// The one call that leaves Vercel is /api/tts, to xAI, when XAI_API_KEY is set in the project.

const rec = require('./recording.json')

const LOCKED = 'This is a recorded demo, so it can’t be changed. The live Keepsake runs on the wearer’s laptop.'
const MAX_TTS = 500 // characters; the app's longest line is an answer with a description

function send(res, status, body) {
  res.statusCode = status
  res.setHeader('Content-Type', 'application/json')
  res.setHeader('Cache-Control', 'no-store')
  res.end(JSON.stringify(body))
}

async function readJson(req) {
  if (req.body && typeof req.body === 'object') return req.body
  const chunks = []
  for await (const c of req) chunks.push(c)
  try { return JSON.parse(Buffer.concat(chunks).toString() || '{}') } catch { return {} }
}

/** Same matching as backend/memory.py parse_query: the longest alias in the question wins. */
function parse(text) {
  const t = ` ${String(text || '').toLowerCase().replace(/[^a-z0-9 ]+/g, ' ')} `
  let best = null
  for (const [cat, aliases] of Object.entries(rec.aliases)) {
    for (const a of aliases) {
      const re = new RegExp(`\\b${a.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}s?\\b`)
      if (re.test(t) && (!best || a.length > best.len)) best = { cat, len: a.length }
    }
  }
  return best && best.cat
}

let voice = { provider: rec.voice.provider, voice_id: rec.voice.voice_id, speed: rec.voice.speed }

function voiceInfo() {
  const grok = Boolean(process.env.XAI_API_KEY)
  return { ...voice, provider: grok ? voice.provider : 'browser', grok_available: grok, voices: rec.voice.voices }
}

module.exports = async (req, res) => {
  const url = new URL(req.url, 'http://x')
  const path = url.pathname.replace(/\/+$/, '')
  const m = req.method

  if (m === 'GET' && path === '/api/health') {
    return send(res, 200, {
      status: 'ok', camera: 'demo', demo: true, recorded: rec.recorded, fps: 0, warning: null, error: null,
      detections: [], capture_enabled: true, person_present: false,
    })
  }
  if (m === 'GET' && path === '/api/objects') return send(res, 200, rec.objects)
  let g = path.match(/^\/api\/objects\/([^/]+)$/)
  if (m === 'GET' && g) {
    const o = rec.objects.find(x => x.object_id === g[1] || x.category === g[1])
    return o ? send(res, 200, o) : send(res, 404, { detail: "Keepsake doesn't track that item" })
  }
  g = path.match(/^\/api\/objects\/([^/]+)\/snapshots$/)
  if (m === 'GET' && g) return send(res, 200, (rec.snapshots[g[1]] || []).slice(0, 20))
  if (m === 'GET' && path === '/api/events') {
    const limit = Math.min(Math.max(Number(url.searchParams.get('limit')) || 50, 1), 200)
    return send(res, 200, rec.events.slice(0, limit))
  }
  if (m === 'POST' && path === '/api/query') {
    const { text } = await readJson(req)
    const cat = parse(text)
    if (!cat) return send(res, 200, { found: false, answer: rec.unknown, object: null, category: null })
    const object = rec.objects.find(o => o.category === cat) || null
    return send(res, 200, { found: Boolean(object && object.seen), answer: rec.answers[cat], object, category: cat })
  }
  if (m === 'GET' && path === '/api/voice') return send(res, 200, voiceInfo())
  if (m === 'PUT' && path === '/api/voice') {
    // Kept for this server instance only: one visitor's choice doesn't change the demo for others.
    const b = await readJson(req)
    if (['grok', 'browser'].includes(b.provider)) voice.provider = b.provider
    if (typeof b.voice_id === 'string' && rec.voice.voices.some(v => v.voice_id === b.voice_id)) voice.voice_id = b.voice_id
    if (typeof b.speed === 'number' && b.speed >= 0.7 && b.speed <= 1.5) voice.speed = b.speed
    return send(res, 200, voiceInfo())
  }
  if (m === 'POST' && path === '/api/tts') {
    const key = process.env.XAI_API_KEY
    if (!key) return send(res, 503, { detail: 'No Grok key on this demo; using the device voice.' })
    const b = await readJson(req)
    const text = String(b.text || '').trim().slice(0, MAX_TTS)
    if (!text) return send(res, 422, { detail: 'Nothing to say' })
    const voice_id = rec.voice.voices.some(v => v.voice_id === b.voice_id) ? b.voice_id : voice.voice_id
    const speed = typeof b.speed === 'number' && b.speed >= 0.7 && b.speed <= 1.5 ? b.speed : voice.speed
    try {
      const r = await fetch('https://api.x.ai/v1/tts', {
        method: 'POST',
        headers: { Authorization: `Bearer ${key}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ text, voice_id, language: 'en', speed }),
      })
      if (!r.ok) return send(res, 502, { detail: `Grok voice failed (${r.status})` })
      res.statusCode = 200
      res.setHeader('Content-Type', 'audio/mpeg')
      res.setHeader('Cache-Control', 'no-store')
      return res.end(Buffer.from(await r.arrayBuffer()))
    } catch {
      return send(res, 502, { detail: 'Grok voice unreachable' })
    }
  }
  if (m === 'GET' && path === '/api/settings') return send(res, 200, { capture_enabled: true })
  if ((m === 'PUT' && path === '/api/settings') || (m === 'DELETE' && path === '/api/memory')) return send(res, 403, { detail: LOCKED })
  if (m === 'GET' && (path === '/api/camera/frame' || path === '/api/camera' || path === '/api/camera/raw')) {
    return send(res, 503, { detail: 'The live camera runs on the wearer’s laptop, not in this recorded demo.' })
  }
  return send(res, 404, { detail: 'Not found' })
}
