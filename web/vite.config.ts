import { defineConfig, loadEnv } from 'vite'
import process from 'node:process'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => ({
  // Keep development caches outside the shared dependency junction.
  cacheDir: '../.runtime/web-vite',
  plugins: [react()],
  server: {
    proxy: {
      '/api/v1': {
        target:
          process.env.API_PROXY_TARGET ||
          loadEnv(mode, process.cwd(), 'API_').API_PROXY_TARGET ||
          'http://127.0.0.1:8000',
        changeOrigin: false,
      },
    },
  },
}))
