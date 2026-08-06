import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  // A single .env.example lives at the repo root (spec §4), not per-app —
  // point Vite there instead of apps/web/ so one .env file covers both apps.
  envDir: '../../',
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    // Scoped to src/ so Vitest's default `**/*.{test,spec}.*` glob doesn't
    // also try to run e2e/*.spec.ts as jsdom tests — those are Playwright
    // specs (real Chromium, `npm run e2e`), a different tool entirely.
    include: ['src/**/*.test.{ts,tsx}'],
  },
})
