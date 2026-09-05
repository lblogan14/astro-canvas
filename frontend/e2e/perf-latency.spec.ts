/**
 * What an edit costs in the browser (phase 13, scope item 2).
 *
 * Design 1.6 asks for a cheap re-run under 300 ms, and 6.3 puts two deliberate debounces in front
 * of it: the store collects a burst of edits before it PUTs the document, and the scheduler waits
 * another `debounce_ms` (250) before auto-running. Both are what stop a slider drag from queueing
 * a run per pixel, and neither is latency the engine spends.
 *
 * So two numbers are recorded. The **re-run latency** is measured on the WebSocket, from the
 * `node.status` that says the node went dirty to the one that says it is done, minus the
 * scheduler's debounce: that is the engine and the transport. The **end-to-end** number is the
 * keystroke-to-new-value time a user actually feels, debounces and all.
 *
 * The engine's cost at five hundred nodes is measured without a browser by
 * `backend/tests/perf/test_engine_scale.py`; what is browser-specific here is how long a document
 * that size takes to become usable at all.
 */
import { expect, test } from './fixtures'

import {
  createWorkflow,
  deleteWorkflow,
  mathChain,
  openWorkflow,
  syntheticWorkflow,
} from './helpers'
import { record } from './perf'

/** `SchedulerConfig.debounce_ms`. */
const SERVER_DEBOUNCE_MS = 250

interface StatusFrame {
  node_id?: string
  type?: string
  state?: string
}

test('a cheap re-run answers within 300 ms of the debounce', async ({ page, request }) => {
  const doc = mathChain()
  await createWorkflow(request, doc)
  /** `node.status` arrivals for the leaf node, in order, with local timestamps. */
  const marks: { state: string; at: number }[] = []
  page.on('websocket', (ws) => {
    ws.on('framereceived', (frame) => {
      if (typeof frame.payload !== 'string') return
      let parsed: StatusFrame
      try {
        parsed = JSON.parse(frame.payload) as StatusFrame
      } catch {
        return
      }
      if (parsed.type === 'node.status' && parsed.node_id === 'sum' && parsed.state)
        marks.push({ state: parsed.state, at: Date.now() })
    })
  })

  try {
    await openWorkflow(page, doc.id)
    const sum = page.getByTestId('node-sum')
    await expect(sum.locator('[data-summary-port="out"]')).toContainText('7')
    const value = page.getByTestId('node-c').locator('[data-param="value"] input')

    // Four edits: the first pays for the parameter form's first render, the rest are the number.
    const endToEnd: number[] = []
    const reRun: number[] = []
    for (const [index, next] of [3, 4, 5, 6].entries()) {
      marks.length = 0
      const started = Date.now()
      await value.fill(String(next))
      await value.press('Enter')
      await expect(sum.locator('[data-summary-port="out"]')).toContainText(
        String(next * next + next + 1),
      )
      const dirty = marks.find((m) => m.state === 'dirty')
      const done = marks.findLast((m) => m.state === 'done')
      expect(dirty, 'the engine reported the node dirty').toBeDefined()
      expect(done, 'the engine reported the node done').toBeDefined()
      if (index > 0) {
        endToEnd.push(Date.now() - started)
        reRun.push(Math.max(0, done!.at - dirty!.at - SERVER_DEBOUNCE_MS))
      }
    }
    record('keystroke to new value on the canvas (4 nodes)', Math.min(...endToEnd), 'ms')
    const latency = record(
      'cheap re-run latency, debounce excluded (4 nodes)',
      Math.min(...reRun),
      'ms',
      300,
    )
    expect(latency).toBeLessThan(300)
  } finally {
    await deleteWorkflow(request, doc.id)
  }
})

test('a 500-node document becomes interactive in a few seconds', async ({ page, request }) => {
  test.slow()
  const doc = syntheticWorkflow(500)
  await createWorkflow(request, doc)
  try {
    const started = Date.now()
    await openWorkflow(page, doc.id)
    await expect.poll(async () => page.locator('.vue-flow__node').count()).toBeGreaterThan(0)
    const open = record('open a 500-node document (cold cache)', Date.now() - started, 'ms', 8000)
    expect(open).toBeLessThan(8000)

    // Fitting the view is the first thing a user does on a graph that size.
    const fit = Date.now()
    await page.getByTestId('fit-view').click()
    await expect(page.getByTestId('canvas')).toBeVisible()
    record('fit 500 nodes into the viewport', Date.now() - fit, 'ms')
  } finally {
    await deleteWorkflow(request, doc.id)
  }
})
