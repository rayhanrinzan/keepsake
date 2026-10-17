import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { sampleApi } from './sample-api.ts'

// /api is proxied to the local FastAPI server so the browser only talks to localhost.
// `npm run dev:sample` serves design-only sample data instead, for UI work without the camera.
export default defineConfig(({ mode }) => ({
  plugins: [react(), tailwindcss(), ...(mode === 'sample' ? [sampleApi()] : [])],
  server: {
    host: '127.0.0.1',
    port: 5173,
    proxy: mode === 'sample' ? undefined : { '/api': 'http://127.0.0.1:8000' },
  },
}))
