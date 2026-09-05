import os from 'node:os'
import path from 'node:path'
import process from 'node:process'
import { fileURLToPath } from 'node:url'

import { defineConfig, devices } from '@playwright/test'

const CI = !!process.env.CI
const BACKEND_PORT = 8765
const FRONTEND_PORT = 5173
const workspace = path.join(os.tmpdir(), 'astro-canvas-e2e-workspace')

/**
 * The `--auth users` server is a *second* pair of servers on their own ports (design 12).
 * Sharing the main backend is not an option: every other spec authenticates with one bearer
 * token, and a login-protected server would break all of them.
 */
const USERS_BACKEND_PORT = 8766
const USERS_FRONTEND_PORT = 5174
const usersData = path.join(os.tmpdir(), 'astro-canvas-e2e-users')

/** Fixed bearer token for the e2e backend (see `e2e/helpers.ts`). */
export const E2E_TOKEN = process.env.ASTRO_CANVAS_TOKEN ?? 'e2e-token'

/** Promoted to superuser by `ASTRO_CANVAS_ADMIN_EMAILS` on the users-mode backend. */
export const ADMIN_EMAIL = 'pi@lab.example'

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
      testIgnore: /users-auth\.spec\.ts/,
    },
    {
      name: 'users',
      testMatch: /users-auth\.spec\.ts/,
      use: {
        ...devices['Desktop Chrome'],
        viewport: { width: 1600, height: 1000 },
        baseURL: `http://127.0.0.1:${USERS_FRONTEND_PORT}`,
        // A lab server has no bearer token: the session is a cookie the login sets.
        extraHTTPHeaders: {},
      },
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
    {
      command:
        `uv run astro-canvas serve --host 127.0.0.1 --port ${USERS_BACKEND_PORT} ` +
        `--auth users --workspace ${JSON.stringify(usersData)}`,
      cwd: fileURLToPath(new URL('../backend', import.meta.url)),
      url: `http://127.0.0.1:${USERS_BACKEND_PORT}/api/health`,
      reuseExistingServer: !CI,
      timeout: 120 * 1000,
      env: {
        ...process.env,
        ASTRO_CANVAS_TOKEN: '',
        ASTRO_CANVAS_ADMIN_EMAILS: ADMIN_EMAIL,
        ASTRO_CANVAS_PROCESS_POOL: 'false',
        ASTRO_CANVAS_WATCH_WORKSPACE: 'false',
        MPLBACKEND: 'Agg',
        QT_QPA_PLATFORM: 'offscreen',
      },
    },
    {
      command: `pnpm dev --port ${USERS_FRONTEND_PORT}`,
      url: `http://127.0.0.1:${USERS_FRONTEND_PORT}`,
      reuseExistingServer: !CI,
      timeout: 120 * 1000,
      env: {
        ...process.env,
        ASTRO_CANVAS_DEV_BACKEND: `http://127.0.0.1:${USERS_BACKEND_PORT}`,
      },
    },
  ],
})
