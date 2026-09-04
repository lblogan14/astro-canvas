import type { APIRequestContext, Page } from '@playwright/test'

import { E2E_TOKEN } from '../playwright.config'

export interface WorkflowDocLike {
  format: 'astro-canvas/workflow'
  version: 1
  id: string
  name: string
  description?: string
  nodes: Record<string, Record<string, unknown>>
  edges: Record<string, { from: [string, string]; to: [string, string] }>
  groups?: Record<string, unknown>
  subgraphs?: Record<string, Record<string, unknown>>
  layouts?: Record<string, unknown>
  meta?: Record<string, unknown>
}

export function uniqueId(prefix: string): string {
  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`
}

/** The backend's `math_chain.json` fixture with a unique id. */
export function mathChain(id = uniqueId('e2e-math')): WorkflowDocLike {
  return {
    format: 'astro-canvas/workflow',
    version: 1,
    id,
    name: `Math chain ${id}`,
    nodes: {
      c: { type: 'core.math.constant', title: 'Two', pos: [80, 80], params: { value: 2.0 } },
      sq: {
        type: 'core.math.expr',
        title: 'Square',
        pos: [360, 80],
        params: { expression: 'x ** 2' },
        linked: ['x'],
      },
      sum: {
        type: 'core.math.expr',
        title: 'Sum',
        pos: [640, 80],
        params: { expression: 'x + y + z', z: 1.0 },
        linked: ['x', 'y'],
      },
      note: {
        type: 'core.note.markdown',
        pos: [80, 300],
        params: { text: '# Sample\nA tiny reactive chain.' },
      },
    },
    edges: {
      e1: { from: ['c', 'out'], to: ['sq', 'x'] },
      e2: { from: ['sq', 'out'], to: ['sum', 'x'] },
      e3: { from: ['c', 'out'], to: ['sum', 'y'] },
    },
    meta: { tags: ['sample'] },
  }
}

/** A grid of `count` constant → expr pairs (all cheap) for load and perf tests. */
export function syntheticWorkflow(count: number, id = uniqueId('e2e-synth')): WorkflowDocLike {
  const nodes: WorkflowDocLike['nodes'] = {}
  const edges: WorkflowDocLike['edges'] = {}
  const columns = Math.ceil(Math.sqrt(count))
  for (let i = 0; i < count; i += 1) {
    const col = i % columns
    const row = Math.floor(i / columns)
    const nodeId = `n${i}`
    if (i % 2 === 0) {
      nodes[nodeId] = {
        type: 'core.math.constant',
        title: `C${i}`,
        pos: [col * 300, row * 220],
        params: { value: i },
      }
    } else {
      nodes[nodeId] = {
        type: 'core.math.expr',
        title: `E${i}`,
        pos: [col * 300, row * 220],
        params: { expression: 'x + 1' },
        linked: ['x'],
      }
      edges[`e${i}`] = { from: [`n${i - 1}`, 'out'], to: [nodeId, 'x'] }
    }
  }
  return {
    format: 'astro-canvas/workflow',
    version: 1,
    id,
    name: `Synthetic ${count}`,
    nodes,
    edges,
  }
}

export async function createWorkflow(
  request: APIRequestContext,
  doc: WorkflowDocLike,
): Promise<void> {
  const response = await request.post('/api/workflows', { data: doc })
  if (response.status() !== 201)
    throw new Error(`create failed: ${response.status()} ${await response.text()}`)
}

export async function deleteWorkflow(request: APIRequestContext, id: string): Promise<void> {
  await request.delete(`/api/workflows/${encodeURIComponent(id)}`)
}

export async function getWorkflow(
  request: APIRequestContext,
  id: string,
): Promise<WorkflowDocLike> {
  const response = await request.get(`/api/workflows/${encodeURIComponent(id)}`)
  return (await response.json()) as WorkflowDocLike
}

/** Open the editor on a workflow; the token travels once via `?token=` and lands in sessionStorage. */
export async function openWorkflow(page: Page, id: string): Promise<void> {
  await page.goto(`/w/${encodeURIComponent(id)}?token=${E2E_TOKEN}`)
  await page.getByTestId('canvas').waitFor()
  await page.getByTestId('ws-status').and(page.locator('[data-status="open"]')).waitFor()
}

/** Strip the fields the server maintains before comparing documents. */
export function comparable(doc: WorkflowDocLike): unknown {
  const meta = { ...doc.meta }
  delete meta.modified
  delete meta.created
  return { ...doc, meta }
}
