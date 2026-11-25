import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Dev: the API (uvicorn ReviewUI.backend.main:app --port 8000) is proxied under /api.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { '/api': 'http://localhost:8000' } },
})
