/**
 * Phase 09 acceptance: the absorption template's Batch layout runs its bundled rows with
 * per-row status, one deliberately broken row fails without stopping the others, the results
 * match the single-run measurement, and a row can be opened back on the canvas.
 */
import type { APIRequestContext, Page } from '@playwright/test'
import { expect, test } from './fixtures'

import { deleteWorkflow, openWorkflow } from './helpers'

const TEMPLATE_ID = 'rbcodes.absorption-line-measurement'

interface Saved {
  doc: { id: string }
  node_errors: Record<string, unknown[]>
}

async function instantiate(request: APIRequestContext, name: string): Promise<Saved> {
  const response = await request.post(
    `/api/templates/${encodeURIComponent(TEMPLATE_ID)}/instantiate`,
    { data: { name } },
  )
  if (response.status() !== 201)
    throw new Error(`instantiate failed: ${response.status()} ${await response.text()}`)
  return (await response.json()) as Saved
}

async function openBatch(page: Page): Promise<void> {
  await page.getByTestId('layout-menu').click()
  await page.getByTestId('layout-batch').click()
  await expect(page.getByTestId('batch-mode')).toBeVisible()
}

/** The state pill of one row, e.g. `Done`. */
function pill(page: Page, row: number) {
  return page.getByTestId(`batch-pill-${row}`)
}

test.describe('batch mode over the absorption template', () => {
  test('runs the bundled rows, keeps going after a bad one, and matches the single run', async ({
    page,
    request,
  }) => {
    const saved = await instantiate(request, 'E2E batch')
    const id = saved.doc.id
    try {
      await openWorkflow(page, id)
      // The canvas run gives the reference measurement for the +-200 km/s window.
      const wCell = page.locator('[data-testid="node-ew"] [data-widget="kv-tile"] dd[data-key="W"]')
      await expect(wCell).toBeVisible({ timeout: 60000 })
      const single = Number.parseFloat(
        ((await wCell.textContent()) ?? '').replace(/[^0-9.eE+-]/g, ''),
      )
      expect(Number.isFinite(single)).toBe(true)

      await openBatch(page)
      // `layouts.batch.rows` points at the bundled CSV, so the grid fills itself.
      await expect(page.getByTestId('batch-row-19')).toBeVisible({ timeout: 30000 })
      await expect(page.getByTestId('batch-map-ew_vmin')).toHaveValue('ew.vmin')
      await expect(page.getByTestId('batch-map-slice_vmin')).toHaveValue('slice.vmin')

      // Break one row: a file that does not exist.
      const broken = page.getByTestId('batch-cell-3-filename')
      await broken.fill('samples/rbcodes/does-not-exist.fits')
      await broken.press('Tab')

      await page.getByTestId('batch-run').click()
      await expect(pill(page, 3)).toHaveText('Error', { timeout: 180000 })
      for (const row of [0, 2, 19]) {
        await expect(pill(page, row)).toHaveText('Done', { timeout: 180000 })
      }
      // The results grid carries the specgui result columns plus the bookkeeping ones.
      const results = page.getByTestId('batch-results')
      await expect(results).toBeVisible({ timeout: 60000 })
      const headers = await results.locator('thead th').allTextContents()
      for (const column of ['W', 'W_e', 'logN', 'status', 'error_message', 'calculation_timestamp'])
        expect(headers).toContain(column)

      // Row 2 is the +-200 km/s window: it must reproduce the canvas measurement.
      const wIndex = headers.indexOf('W')
      const row2 = results.locator('[data-testid="batch-result-2"] td')
      const batchW = Number.parseFloat((await row2.nth(wIndex).textContent()) ?? '')
      expect(batchW).toBeCloseTo(single, 2)
      const statusIndex = headers.indexOf('status')
      await expect(row2.nth(statusIndex)).toHaveText('done')
      const errorRow = results.locator('[data-testid="batch-result-3"] td')
      await expect(errorRow.nth(statusIndex)).toHaveText('error')
      await expect(errorRow.nth(headers.indexOf('error_message'))).not.toBeEmpty()

      // "Open in canvas" writes that row's parameters onto the graph.
      await page.getByTestId('batch-open-0').click()
      await expect(page.getByTestId('canvas')).toBeVisible()
      await expect(page.getByTestId('toast')).toContainText('Row 1')
      await expect
        .poll(
          async () => {
            const doc = (await (await request.get(`/api/workflows/${id}`)).json()) as {
              nodes: Record<string, { params: Record<string, unknown> }>
            }
            return [doc.nodes['ew']?.params?.['vmax'], doc.nodes['slice']?.params?.['vmax']]
          },
          { timeout: 20000 },
        )
        .toEqual([100, 1500])
    } finally {
      await deleteWorkflow(request, id)
    }
  })

  test('imports a specgui batch CSV and maps its columns automatically', async ({
    page,
    request,
  }) => {
    const saved = await instantiate(request, 'E2E batch import')
    const id = saved.doc.id
    try {
      await openWorkflow(page, id)
      await openBatch(page)
      await page.getByTestId('batch-paste').click()
      await page
        .getByTestId('batch-paste-area')
        .fill(
          [
            'filename,redshift,transition,transition_name,slice_vmin,slice_vmax,ew_vmin,ew_vmax,linelist,method',
            'samples/rbcodes/sdss1.fits,1.3855,2796.35,MgII 2796,-1200,1200,-180,180,atom,closest',
            'samples/rbcodes/sdss1.fits,1.3855,2803.53,MgII 2803,-1200,1200,-180,180,atom,closest',
          ].join('\n'),
        )
      await page.getByTestId('batch-paste-apply').click()

      await expect(page.getByTestId('toast')).toContainText('specgui')
      await expect(page.getByTestId('batch-row-1')).toBeVisible()
      // The two velocity windows map onto different nodes, as in launch_specgui -b.
      await expect(page.getByTestId('batch-map-slice_vmin')).toHaveValue('slice.vmin')
      await expect(page.getByTestId('batch-map-slice_vmax')).toHaveValue('slice.vmax')
      await expect(page.getByTestId('batch-map-ew_vmin')).toHaveValue('ew.vmin')
      await expect(page.getByTestId('batch-map-ew_vmax')).toHaveValue('ew.vmax')
      await expect(page.getByTestId('batch-map-filename')).toHaveValue('load.path')
      await expect(page.getByTestId('batch-map-redshift')).toHaveValue('redshift.z')
      // Result columns of the specgui export are imported but never bound.
      await expect(page.getByTestId('batch-map-transition_name')).toHaveValue('')

      await page.getByTestId('batch-select-1').check()
      await page.getByTestId('batch-run-selected').click()
      await expect(pill(page, 1)).toHaveText('Done', { timeout: 180000 })
      await expect(pill(page, 0)).toHaveText('Pending')
    } finally {
      await deleteWorkflow(request, id)
    }
  })

  test('cancelling a batch stops the queued rows', async ({ page, request }) => {
    const saved = await instantiate(request, 'E2E batch cancel')
    const id = saved.doc.id
    try {
      await openWorkflow(page, id)
      await openBatch(page)
      // Unique redshifts: every row is real work, so none of them can finish from the cache.
      // The e2e workspace outlives a run, so the offset also varies between runs — otherwise
      // the second run of this test finds all 24 rows already cached and nothing to cancel.
      const seed = Date.now() % 100000
      const header =
        'filename,redshift,transition,slice_vmin,slice_vmax,ew_vmin,ew_vmax,linelist,method'
      const rows = Array.from(
        { length: 24 },
        (_, i) =>
          `samples/rbcodes/sdss1.fits,${(1.3855 + (seed * 24 + i) * 1e-7).toFixed(7)},2796.35,-1500,1500,-200,200,atom,closest`,
      )
      await page.getByTestId('batch-paste').click()
      await page.getByTestId('batch-paste-area').fill([header, ...rows, ''].join('\n'))
      await page.getByTestId('batch-paste-apply').click()
      await expect(page.getByTestId('batch-row-23')).toBeVisible()

      await page.getByTestId('batch-run').click()
      await page.getByTestId('batch-cancel').click()
      // The batch ends (Cancel goes disabled again) with nothing left running.
      await expect(page.getByTestId('batch-cancel')).toBeDisabled({ timeout: 120000 })
      const states = await page
        .locator('[data-testid^="batch-row-"]')
        .evaluateAll((cells) => cells.map((cell) => cell.getAttribute('data-state')))
      expect(states).not.toContain('running')
      expect(states.filter((state) => state === 'done').length).toBeLessThan(rows.length)
    } finally {
      await deleteWorkflow(request, id)
    }
  })
})
