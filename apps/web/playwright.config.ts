import { defineConfig, devices } from '@playwright/test'

/**
 * Critical-flow E2E (spec §13.5) against a real Chromium browser. Only the
 * frontend dev server is started here — the API is a separate long-running
 * process this config doesn't own (it needs a migrated, catalog-populated
 * Postgres first, which is a data-setup concern, not a server-lifecycle
 * one). `make e2e` boots the API around this; CI's `e2e` job does the same
 * as its own step. Run directly with `npx playwright test` once both the
 * API (`make dev-api`) and Postgres (`make db-start`) are already up.
 */
export default defineConfig({
  testDir: './e2e',
  // One long sequential journey (register through re-login), not many
  // independent cases — each step depends on state the previous step left
  // behind, so parallel workers would just race each other.
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  // 13 real network round-trips plus two axe scans against localhost is
  // still fast, but CI runners are slower than a dev machine — default 30s
  // leaves too little margin.
  timeout: 60_000,
  reporter: process.env.CI ? [['html', { open: 'never' }], ['line']] : 'list',
  use: {
    baseURL: process.env.E2E_BASE_URL ?? 'http://localhost:5173',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
  webServer: {
    command: 'npm run dev -- --port 5173 --strictPort',
    url: 'http://localhost:5173',
    reuseExistingServer: !process.env.CI,
    timeout: 30_000,
  },
})
