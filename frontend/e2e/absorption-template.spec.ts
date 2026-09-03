/**
 * Phase 05 acceptance: the rbcodes absorption-line template runs end to end, the continuum
 * editor previews a fit as masks are added, and Apply re-runs the graph so W changes.
 * The backend copies the bundled sample data into `<workspace>/samples/rbcodes` on start.
 */
import { expect, test, type APIRequestContext, type Page } from '@playwright/test'

import { deleteWorkflow, openWorkflow } from './helpers'

const TEMPLATE_ID = 'rbcodes.absorption-line-measurement'

interface Saved {
  doc: { id: string; name: string; nodes: Record<string, unknown> }
  node_errors: Record<string, unknown[]>
}

async function instantiate(request: APIRequestContext, name: string): Promise<Saved> {
  const response = await request.post(
    `/api/templates/${encodeURIComponent(TEMPLATE_ID)}/instantiate`,
    {
      data: { name },
    },
  )
  if (response.status() !== 201)
    throw new Error(`instantiate failed: ${response.status()} ${await response.text()}`)
  return (await response.json()) as Saved
}

function nodeRoot(page: Page, nodeId: string) {
  return page.locator(`[data-testid="node-${nodeId}"]`)
}

async function readW(page: Page): Promise<number> {
  const cell = nodeRoot(page, 'ew').locator('[data-widget="kv-tile"] dd[data-key="W"]')
  await expect(cell).toBeVisible({ timeout: 30000 })
  const text = (await cell.textContent()) ?? ''
  const value = Number.parseFloat(text.replace(/[^0-9eE+.-]/g, ''))
  expect(Number.isFinite(value)).toBe(true)
  return value
}

test.describe('absorption-line template', () => {
  test('template lists in the API, runs to an EWMeasurement, and the continuum editor re-fits', async ({
    page,
    request,
  }) => {
    const templates = (await (await request.get('/api/templates')).json()) as { id: string }[]
    expect(templates.map((t) => t.id)).toContain(TEMPLATE_ID)
    const saved = await instantiate(request, 'E2E absorption')
    const id = saved.doc.id
    expect(saved.node_errors).toEqual({})
    try {
      await openWorkflow(page, id)
      // Every node in the template reaches Done (cheap path, auto-run on open).
      for (const nodeId of ['load', 'redshift', 'transition', 'slice', 'continuum', 'ew', 'save']) {
        await expect(nodeRoot(page, nodeId).getByTestId('status-badge')).toHaveText(/done/i, {
          timeout: 60000,
        })
      }
      const before = await readW(page)
      // rbcodes 2.4.0 gives W = 2.071 A for MgII 2796 with the template masks.
      expect(before).toBeGreaterThan(2.0)
      expect(before).toBeLessThan(2.15)

      // Open the continuum-mask editor from the node header button.
      await nodeRoot(page, 'continuum').getByTestId('node-editor').click()
      const editor = page.getByTestId('editor')
      await editor.waitFor()
      await expect(editor).toHaveAttribute('data-editor', 'continuum-mask')
      await expect(editor.locator('[data-testid="mask-item"]')).toHaveCount(2)
      const status = editor.getByTestId('editor-fit-status')
      // The initial preview fit (the committed params) completes and reports the BIC order.
      await expect(status).toHaveAttribute('data-pending', 'false', { timeout: 15000 })
      await expect(status).toContainText(/ms/)
      await expect(editor.locator('[data-testid="bic-table"] tbody tr')).toHaveCount(8)

      // Add a third mask through the form: the preview re-fits within the 300 ms budget.
      await editor.getByTestId('mask-lo').fill('-1400')
      await editor.getByTestId('mask-hi').fill('-900')
      const statusBefore = (await status.textContent()) ?? ''
      const started = Date.now()
      await editor.getByTestId('mask-add').click()
      await expect(editor.locator('[data-testid="mask-item"]')).toHaveCount(3)
      // The transient "Fitting" state can complete between polls (debounce 80 ms + fit ~10 ms),
      // so wait for the new result rather than for the pending flag.
      await expect(status).not.toHaveText(statusBefore, { timeout: 5000 })
      await expect(status).toHaveAttribute('data-pending', 'false', { timeout: 5000 })
      const roundTrip = Date.now() - started
      const serverMs = Number(/(\d+) ms/.exec((await status.textContent()) ?? '')?.[1] ?? 'NaN')
      console.log(`continuum preview: server ${serverMs} ms, round trip ${roundTrip} ms`)
      expect(serverMs).toBeLessThan(300)
      expect(roundTrip).toBeLessThan(1500)

      // Fix the order to 0 through the BIC table, then Apply: params change and the graph
      // re-runs downstream on its own (cheap path), so W differs from the first measurement.
      await editor.locator('[data-testid="bic-table"] tbody tr').first().click()
      await expect(editor.getByTestId('continuum-order')).toHaveValue('0')
      await editor.getByTestId('editor-apply').click()
      await expect(editor).toHaveCount(0)
      await expect
        .poll(
          async () => {
            const response = await request.get(`/api/workflows/${encodeURIComponent(id)}`)
            const doc = (await response.json()) as {
              nodes: Record<string, { params?: Record<string, unknown> }>
            }
            return doc.nodes['continuum']?.params
          },
          { timeout: 15000 },
        )
        .toMatchObject({
          order: 0,
          optimize_order: false,
          masks: [
            [-1400, -900],
            [-300, 250],
            [500, 1000],
          ],
        })
      await expect(nodeRoot(page, 'ew').getByTestId('status-badge')).toHaveText(/done/i, {
        timeout: 60000,
      })
      await expect.poll(async () => readW(page), { timeout: 30000 }).not.toBe(before)
      const after = await readW(page)
      console.log(`W before ${before} A, after ${after} A`)
      expect(Math.abs(after - before)).toBeGreaterThan(1e-4)
    } finally {
      await deleteWorkflow(request, id)
    }
  })

  test('the Workflows panel lists templates and creates a workflow from one', async ({
    page,
    request,
  }) => {
    const created: string[] = []
    try {
      await page.goto(`/?token=${process.env.ASTRO_CANVAS_TOKEN ?? 'e2e-token'}`)
      await page.getByTestId('canvas').waitFor()
      // Workflows panel -> Templates -> Use.
      await page.getByTestId('toggle-workflows').click()
      const panel = page.getByTestId('workflows-panel')
      await panel.waitFor()
      await panel.getByTestId('toggle-templates').click()
      const row = panel.locator(`[data-template-id="${TEMPLATE_ID}"]`)
      await row.waitFor()
      // The home route may auto-open the most recent workflow, so take the new id from the
      // instantiate response rather than from whatever URL appears first.
      const instantiated = page.waitForResponse(
        (r) => r.url().includes('/instantiate') && r.request().method() === 'POST',
      )
      await row.getByTestId('template-use').click()
      const saved = (await (await instantiated).json()) as Saved
      const id = saved.doc.id
      created.push(id)
      await page.waitForURL(new RegExp(`/w/${id}`), { timeout: 15000 })
      await expect(page.locator('[data-testid^="node-"][data-node-id]')).toHaveCount(9, {
        timeout: 15000,
      })
      await expect(nodeRoot(page, 'ew').getByTestId('status-badge')).toHaveText(/done/i, {
        timeout: 60000,
      })
      // The range-select editor opens on the slice node and shows the current window.
      await nodeRoot(page, 'slice').getByTestId('node-editor').click()
      const editor = page.getByTestId('editor')
      await expect(editor).toHaveAttribute('data-editor', 'range-select')
      await expect(editor.getByTestId('range-vmin')).toHaveValue('-1500')
      await expect(editor.getByTestId('range-vmax')).toHaveValue('1500')
      await editor.getByTestId('editor-close').click()
      await expect(editor).toHaveCount(0)
    } finally {
      for (const id of created) await deleteWorkflow(request, id)
    }
  })
})
