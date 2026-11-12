import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Build landet direkt in app/static -> FastAPI liefert die SPA aus,
// der LXC braucht dafuer kein Node (dist wird committed).
export default defineConfig({
  plugins: [react()],
  base: '/',
  build: {
    outDir: '../app/static',
    emptyOutDir: true,
  },
  server: {
    proxy: { '/api': 'http://127.0.0.1:8000' },
  },
})
