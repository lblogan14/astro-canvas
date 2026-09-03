import os from 'node:os'
import path from 'node:path'
import process from 'node:process'
import { fileURLToPath } from 'node:url'

import { defineConfig, devices } from '@playwright/test'

const CI = !!process.env.CI
const BACKEND_PORT = 8765
const FRONTEND_PORT = 5173
const workspace = path.join(os.tmpdir(), 'astro-canvas-e2e-workspace')

/** Fixed bearer token for the e2e backend (see `e2e/helpers.ts`). */
export const E2E_TOKEN = process.env.ASTRO_CANVAS_TOKEN ?? 'e2e-token'

/**
 * E2E runs against the real backend: Playwright starts `astro-canvas serve` (via uv) and the
 * Vite dev server (which proxies /api and /ws). Locally, already-running servers are reused; a
 * reused backend must have been started with `ASTRO_CANVAS_TOKEN=e2e-token`.
 * See https://playwright.dev/docs/test-configuration.
 */
export default defineConfig({
  testDir: './e2e',
  timeout: 60 * 1000,
  expect: { timeout: 10000 },
  fullyParallel: true,
  forbidOnly: CI,
  retries: CI ? 2 : 0,
  workers: CI ? 1 : undefined,
  reporter: CI ? [['github'], ['html', { open: 'never' }]] : [['list']],
  use: {
    baseURL: `http://127.0.0.1:${FRONTEND_PORT}`,
    trace: 'on-first-retry',
    headless: true,
    extraHTTPHeaders: { Authorization: `Bearer ${E2E_TOKEN}` },
  },
  projects: [
    {
      name: 'chromium',
      // A roomy canvas: the shell keeps a library, an inspector and a toolbar around it.
      use: { ...devices['Desktop Chrome'], viewport: { width: 1600, height: 1000 } },
    },
  ],
  webServer: [
    {
      command: `uv run astro-canvas serve --host 127.0.0.1 --port ${BACKEND_PORT}`,
      cwd: fileURLToPath(new URL('../backend', import.meta.url)),
      url: `http://127.0.0.1:${BACKEND_PORT}/api/health`,
      reuseExistingServer: !CI,
      timeout: 120 * 1000,
      env: {
        ...process.env,
        ASTRO_CANVAS_WORKSPACE: workspace,
        ASTRO_CANVAS_TOKEN: E2E_TOKEN,
        ASTRO_CANVAS_PROCESS_POOL: 'false',
        MPLBACKEND: 'Agg',
        QT_QPA_PLATFORM: 'offscreen',
      },
    },
    {
      command: `pnpm dev --port ${FRONTEND_PORT}`,
      url: `http://127.0.0.1:${FRONTEND_PORT}`,
      reuseExistingServer: !CI,
      timeout: 120 * 1000,
    },
  ],
})
