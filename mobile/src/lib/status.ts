import type { Health } from './api'

/** The camera status the web app shows in its sidebar: "Watching", "Camera paused", "Offline"… */
export function cameraStatus(health: Health | null, offline: boolean): { label: string; color: string } {
  if (offline) return { label: 'Offline', color: '#ff6b6b' }
  if (!health) return { label: 'Connecting…', color: 'rgba(255,255,255,0.4)' }
  if (health.camera === 'active' && health.warning) return { label: 'Camera paused', color: '#ffb27a' }
  if (health.camera === 'active') return { label: 'Watching', color: '#3ddc97' }
  if (health.camera === 'disabled') return { label: 'Camera off', color: 'rgba(255,255,255,0.4)' }
  return { label: 'Camera unavailable', color: '#ffb27a' }
}
