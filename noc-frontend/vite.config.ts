import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 3000,
    proxy: {
      '/graphql': { target: 'http://localhost:4000', changeOrigin: true, ws: true },
      // Legacy insights-api proxy (classification, drift — existing endpoints)
      '/api/insights': {
        target: 'http://localhost:4001',
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/api\/insights/, ''),
      },
      // New facility/thermal/power/alerts/reports/analytics endpoints
      // These are new routes added to insights-api (port 4001)
      '/api/facility': { target: 'http://localhost:4001', changeOrigin: true },
      '/api/thermal':  { target: 'http://localhost:4001', changeOrigin: true },
      '/api/power':    { target: 'http://localhost:4001', changeOrigin: true },
      '/api/alerts':   { target: 'http://localhost:4001', changeOrigin: true },
      '/api/reports':  { target: 'http://localhost:4001', changeOrigin: true },
      '/api/analytics':{ target: 'http://localhost:4001', changeOrigin: true },
      '/api/drift':    { target: 'http://localhost:4001', changeOrigin: true },
      '/api/classification': { target: 'http://localhost:4001', changeOrigin: true },
      '/api/topology': { target: 'http://localhost:4001', changeOrigin: true },
      '/api/settings': { target: 'http://localhost:4001', changeOrigin: true },
      '/api/eventing': {
        target: 'http://localhost:4002',
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/api\/eventing/, ''),
      },
    },
  },
  build: { outDir: 'dist', sourcemap: false },
})
