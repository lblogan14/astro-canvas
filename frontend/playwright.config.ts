import process from 'node:process'

import { defineConfig, devices } from '@playwright/test'

import type { E2EWorkerOptions } from './e2e/fixtures'

const CI = !!process.env.CI

/**
 * E2E runs against the **bundled SPA**: `astro_canvas/static/` served by the app itself, which is
 * what a user installs (`task build:spa` populates it, `task test:e2e` runs that first). There is
 * no `webServer` here and no Vite dev server -- every worker starts its own backend from
 * `e2e/fixtures.ts`, on its own port with its own workspace, so the suite is parallel-safe.
 *
 * `perf` is a project of its own because a frame-rate gate needs the machine to itself; it is not
 * part of the default run (`task test:e2e:perf`).
 *
 * See https://playwright.dev/docs/test-configuration.
 */
export default defineConfig<object, E2EWorkerOptions>({
  testDir: './e2e',
  timeout: 90 * 1000,
  expect: { timeout: 10000 },
  fullyParallel: true,
  forbidOnly: CI,
  retries: CI ? 2 : 0,
  // One backend per worker costs ~350 MB, so the count is capped rather than left to the CPU.
  workers: Number(process.env.PLAYWRIGHT_WORKERS) || (CI ? 2 : 4),
  reporter: CI ? [['github'], ['html', { open: 'never' }]] : [['list']],
  use: {
    trace: 'on-first-retry',
    headless: true,
  },
  projects: [
    {
      name: 'chromium',
      // A roomy canvas: the shell keeps a library, an inspector and a toolbar around it.
      use: {
        ...devices['Desktop Chrome'],
        viewport: { width: 1600, height: 1000 },
        serverAuth: 'token',
        portBase: 8800,
      },
      testIgnore: [/users-auth\.spec\.ts/, /perf-500\.spec\.ts/],
    },
    {
      name: 'users',
      testMatch: /users-auth\.spec\.ts/,
      use: {
        ...devices['Desktop Chrome'],
        viewport: { width: 1600, height: 1000 },
        serverAuth: 'users',
        portBase: 8850,
      },
    },
    {
      name: 'perf',
      testMatch: /perf-500\.spec\.ts/,
      use: {
        ...devices['Desktop Chrome'],
        viewport: { width: 1600, height: 1000 },
        serverAuth: 'token',
        portBase: 8890,
      },
    },
  ],
})
