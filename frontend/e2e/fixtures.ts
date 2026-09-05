/**
 * Per-worker backends, so the Playwright suite is parallel-safe (phase 13, scope item 1).
 *
 * Until phase 12 every spec talked to one server on 8765 with one workspace, and one Vite dev
 * server proxied to it. That shared state is what made 10 of 48 specs fail at the default worker
 * count: a pack disabled in the Manager spec vanished from another spec's library, two specs
 * wrote `outputs/...` under the same name, and the perf spec measured frames while four other
 * browsers competed for the CPU.
 *
 * Instead, each Playwright worker gets its own `astro-canvas serve` on its own port with its own
 * workspace and config directory, and the SPA is served by that backend from
 * `astro_canvas/static/` -- the bundle a user actually runs. There is no dev server in the loop,
 * which also removes Vite's cold-compile timeouts from the e2e failure modes.
 *
 * Environment:
 * - `ASTRO_CANVAS_E2E_WHEEL=1` runs the built wheels from `backend/dist` in an isolated
 *   environment instead of the source checkout (the nightly matrix does this).
 * - `ASTRO_CANVAS_E2E_KEEP_WORKSPACE=1` keeps a worker's workspace between runs, so a repeat
 *   local run starts with a warm blob cache.
 * - `ASTRO_CANVAS_E2E_VERBOSE=1` streams the backends' logs into the test output.
 */
import { spawn } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import process from 'node:process'
import { fileURLToPath } from 'node:url'

import type { ChildProcess } from 'node:child_process'
import { test as base, expect } from '@playwright/test'

/** Fixed bearer token for every token-mode e2e backend. */
export const E2E_TOKEN = 'e2e-token'

/** Promoted to superuser by `ASTRO_CANVAS_ADMIN_EMAILS` on a users-mode backend. */
export const ADMIN_EMAIL = 'pi@lab.example'

/** Which server a project wants; `users` is the `--auth users` lab tier (design 12). */
export type ServerAuth = 'token' | 'users'

export interface E2EWorkerOptions {
  /** Auth mode of this project's backend. */
  serverAuth: ServerAuth
  /** First port of this project's range; the worker adds its parallel index. */
  portBase: number
}

export interface Backend {
  /** Origin the SPA and the API are served from. */
  url: string
  /** Bearer token, or `''` on a users-mode server where the session is a cookie. */
  token: string
  /** Workspace root this worker's server opened. */
  workspace: string
}

const BACKEND_DIR = fileURLToPath(new URL('../../backend', import.meta.url))
const STATIC_INDEX = path.join(BACKEND_DIR, 'src', 'astro_canvas', 'static', 'index.html')
const ROOT = path.join(os.tmpdir(), 'astro-canvas-e2e')
const KEEP = process.env.ASTRO_CANVAS_E2E_KEEP_WORKSPACE === '1'
const USE_WHEEL = process.env.ASTRO_CANVAS_E2E_WHEEL === '1'
/** Stream the backend's own log to stdout; the last 400 chunks are kept for failures either way. */
const VERBOSE = process.env.ASTRO_CANVAS_E2E_VERBOSE === '1'
const START_TIMEOUT_MS = 180_000

/**
 * `uv run astro-canvas serve ...` -- from the checkout, or from the built wheels.
 *
 * The wheel form is the same `uv run --isolated --no-project --with ...` shape `task build:smoke`
 * uses, so the run really is against the distribution and not against `src/`.
 */
function serveCommand(): { command: string; args: string[] } {
  if (!USE_WHEEL) return { command: 'uv', args: ['run', 'astro-canvas'] }
  const dist = path.join(BACKEND_DIR, 'dist')
  const wheels = fs
    .readdirSync(dist)
    .filter((name) => name.endsWith('.whl'))
    .sort()
  if (wheels.length === 0)
    throw new Error(`ASTRO_CANVAS_E2E_WHEEL=1 but ${dist} holds no wheels - run \`task build\``)
  const args = ['run', '--isolated', '--no-project']
  for (const wheel of wheels) args.push('--with', path.join(dist, wheel))
  args.push('astro-canvas')
  return { command: 'uv', args }
}

/** Terminate the server and everything `uv run` started under it. */
async function stop(child: ChildProcess): Promise<void> {
  if (child.exitCode !== null || child.signalCode !== null) return
  const done = new Promise<void>((resolve) => child.once('exit', () => resolve()))
  if (process.platform === 'win32' && child.pid !== undefined) {
    // SIGTERM does not reach the python process `uv run` spawned; taskkill /T does.
    spawn('taskkill', ['/pid', String(child.pid), '/T', '/F'], { stdio: 'ignore' })
  } else if (child.pid !== undefined) {
    try {
      process.kill(-child.pid, 'SIGTERM')
    } catch {
      child.kill('SIGKILL')
    }
  }
  await Promise.race([done, new Promise<void>((resolve) => setTimeout(resolve, 10_000))])
}

async function waitForHealth(url: string, child: ChildProcess, log: string[]): Promise<void> {
  const deadline = Date.now() + START_TIMEOUT_MS
  while (Date.now() < deadline) {
    if (child.exitCode !== null)
      throw new Error(`backend exited with ${child.exitCode}\n${log.join('')}`)
    try {
      const response = await fetch(`${url}/api/health`)
      if (response.ok) return
    } catch {
      // not listening yet
    }
    await new Promise((resolve) => setTimeout(resolve, 250))
  }
  throw new Error(`no /api/health on ${url} within ${START_TIMEOUT_MS} ms\n${log.join('')}`)
}

async function startBackend(
  auth: ServerAuth,
  port: number,
  slot: string,
  log: string[],
): Promise<{ backend: Backend; child: ChildProcess }> {
  if (!fs.existsSync(STATIC_INDEX))
    throw new Error(
      `the e2e suite runs against the bundled SPA, but ${STATIC_INDEX} is missing - ` +
        'run `task build:spa` (or `task test:e2e`, which does it for you)',
    )
  const workspace = path.join(ROOT, slot, 'workspace')
  const configDir = path.join(ROOT, slot, 'config')
  if (!KEEP) fs.rmSync(path.join(ROOT, slot), { recursive: true, force: true })
  fs.mkdirSync(workspace, { recursive: true })
  fs.mkdirSync(configDir, { recursive: true })

  const { command, args } = serveCommand()
  const serve = ['serve', '--host', '127.0.0.1', '--port', String(port), '--auth', auth]
  const child = spawn(command, [...args, ...serve], {
    cwd: BACKEND_DIR,
    detached: process.platform !== 'win32',
    stdio: ['ignore', 'pipe', 'pipe'],
    env: {
      ...process.env,
      ASTRO_CANVAS_WORKSPACE: workspace,
      ASTRO_CANVAS_CONFIG_DIR: configDir,
      ASTRO_CANVAS_TOKEN: auth === 'token' ? E2E_TOKEN : '',
      ASTRO_CANVAS_ADMIN_EMAILS: auth === 'users' ? ADMIN_EMAIL : '',
      ASTRO_CANVAS_PROCESS_POOL: 'false',
      ASTRO_CANVAS_WATCH_WORKSPACE: auth === 'users' ? 'false' : 'true',
      MPLBACKEND: 'Agg',
      QT_QPA_PLATFORM: 'offscreen',
    },
  })
  const keep = (chunk: Buffer): void => {
    const text = chunk.toString()
    if (VERBOSE) process.stdout.write(text)
    log.push(text)
    if (log.length > 400) log.splice(0, log.length - 400)
  }
  child.stdout?.on('data', keep)
  child.stderr?.on('data', keep)

  const url = `http://127.0.0.1:${port}`
  try {
    await waitForHealth(url, child, log)
  } catch (error) {
    await stop(child)
    throw error
  }
  return { backend: { url, token: auth === 'token' ? E2E_TOKEN : '', workspace }, child }
}

export const test = base.extend<object, E2EWorkerOptions & { backend: Backend }>({
  serverAuth: ['token', { scope: 'worker', option: true }],
  portBase: [8800, { scope: 'worker', option: true }],

  backend: [
    async ({ serverAuth, portBase }, use, workerInfo) => {
      const port = portBase + workerInfo.parallelIndex
      const slot = `${workerInfo.project.name}-${workerInfo.parallelIndex}`
      const log: string[] = []
      const { backend, child } = await startBackend(serverAuth, port, slot, log)
      try {
        await use(backend)
      } finally {
        await stop(child)
      }
    },
    { scope: 'worker' },
  ],

  // The two request-level options follow the worker's own server.
  baseURL: async ({ backend }, use) => {
    await use(backend.url)
  },
  extraHTTPHeaders: async ({ backend }, use) => {
    await use(backend.token ? { Authorization: `Bearer ${backend.token}` } : {})
  },
})

export { expect }
