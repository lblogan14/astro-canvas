/**
 * Phase 04 acceptance: workspace files → loader nodes → inline previews → full-size viewer.
 * The backend copies the bundled sample data into `<workspace>/samples/rbcodes` on start.
 */
import { expect, test, type Page } from '@playwright/test'

import { createWorkflow, deleteWorkflow, openWorkflow, uniqueId } from './helpers'

function emptyWorkflow(id: string) {
  return {
    format: 'astro-canvas/workflow' as const,
    version: 1 as const,
    id,
    name: `Data load ${id}`,
    nodes: {},
    edges: {},
  }
}

async function openWorkspacePanel(page: Page): Promise<void> {
  await page.getByTestId('toggle-workspace').click()
  await page.getByTestId('workspace-panel').waitFor()
  await expect(page.getByTestId('workspace-root')).not.toBeEmpty()
}

async function revealSample(page: Page, name: string): Promise<void> {
  const panel = page.getByTestId('workspace-panel')
  const samples = panel.locator('[data-testid="workspace-entry"][data-path="samples"]')
  await samples.waitFor()
  if ((await panel.locator('[data-path="samples/rbcodes"]').count()) === 0) await samples.click()
  const pack = panel.locator('[data-testid="workspace-entry"][data-path="samples/rbcodes"]')
  await pack.waitFor()
  const file = panel.locator(`[data-testid="workspace-entry"][data-path="samples/rbcodes/${name}"]`)
  if ((await file.count()) === 0) await pack.click()
  await file.waitFor()
  await file.click()
}

test.describe('data loading and previews', () => {
  test('sample spectrum → Load node → uPlot thumbnail → Plotly viewer with server re-sampling', async ({
    page,
    request,
  }) => {
    const id = uniqueId('e2e-data')
    await createWorkflow(request, emptyWorkflow(id))
    try {
      await openWorkflow(page, id)
      await openWorkspacePanel(page)
      await revealSample(page, 'sdss1.fits')
      await page.getByTestId('workspace-add').click()

      const node = page.locator('[data-testid^="node-"][data-node-id]').first()
      await node.waitFor()
      await expect(node.locator('[data-param="path"] input')).toHaveValue(
        'samples/rbcodes/sdss1.fits',
      )
      await expect(node.getByTestId('status-badge')).toHaveText(/done/i, { timeout: 20000 })
      const doneAt = Date.now()
      const thumb = node.locator(
        '[data-preview-kind="spectrum-thumb"] [data-widget="uplot-line"] canvas',
      )
      await thumb.waitFor({ timeout: 5000 })
      const thumbLatency = Date.now() - doneAt
      console.log(`uPlot thumbnail appeared ${thumbLatency} ms after the node finished`)
      expect(thumbLatency).toBeLessThan(1500)
      const points = Number(
        await node.locator('[data-widget="uplot-line"]').getAttribute('data-points'),
      )
      expect(points).toBeGreaterThan(100)
      expect(points).toBeLessThanOrEqual(4000)

      await node.getByTestId('preview-expand').click()
      const viewer = page.getByTestId('viewer')
      await viewer.waitFor()
      await expect(viewer).toHaveAttribute('data-renderer', 'spectrum-thumb')
      const plot = viewer.locator('.js-plotly-plot')
      await plot.waitFor({ timeout: 30000 })
      await expect(viewer.getByTestId('viewer-points')).toContainText(/of \d+ points/, {
        timeout: 15000,
      })
      const before = await viewer.getByTestId('viewer-points').textContent()

      // Box-zoom equivalent: relayout the x axis; the viewer asks the server for that slice.
      await plot.evaluate(async (el) => {
        const gd = el as unknown as { layout: { xaxis: { range: [number, number] } } }
        const win = window as unknown as {
          Plotly?: { relayout: (e: Element, u: object) => Promise<void> }
        }
        const [lo, hi] = gd.layout.xaxis.range
        const width = hi - lo
        if (win.Plotly)
          await win.Plotly.relayout(el, { 'xaxis.range': [lo + width * 0.45, lo + width * 0.5] })
        else el.dispatchEvent(new CustomEvent('plotly_relayout'))
      })
      await expect
        .poll(async () => viewer.getByTestId('viewer-points').textContent(), { timeout: 15000 })
        .not.toBe(before)
      const after = await viewer.getByTestId('viewer-points').textContent()
      const shown = Number(/^(\d+) of/.exec(after ?? '')?.[1] ?? 0)
      const total = Number(/of (\d+) points/.exec(after ?? '')?.[1] ?? 0)
      expect(total).toBeGreaterThan(3000)
      expect(shown).toBeLessThan(total)
      await page.getByTestId('viewer-close').click()
      await expect(viewer).toHaveCount(0)
    } finally {
      await deleteWorkflow(request, id)
    }
  })

  test('uploaded ASCII spectrum → node via double-click; cube → white-light thumb and WCS readout', async ({
    page,
    request,
  }) => {
    const id = uniqueId('e2e-upload')
    await createWorkflow(request, emptyWorkflow(id))
    try {
      await openWorkflow(page, id)
      await openWorkspacePanel(page)

      // Upload through the panel's file input (an ASCII spectrum with a header line).
      const rows = ['wave flux flux_err']
      for (let i = 0; i < 500; i += 1) rows.push(`${5000 + i * 0.5} ${1 + Math.sin(i / 20)} 0.05`)
      const fileName = `e2e-${Date.now().toString(36)}.dat`
      await page
        .getByTestId('workspace-panel')
        .locator('input[type="file"]')
        .setInputFiles({
          name: fileName,
          mimeType: 'text/plain',
          buffer: Buffer.from(rows.join('\n'), 'utf-8'),
        })
      const uploaded = page.locator(
        `[data-testid="workspace-entry"][data-path="uploads/${fileName}"]`,
      )
      await uploaded.waitFor({ timeout: 15000 })
      await uploaded.dblclick()
      const node = page.locator('[data-testid^="node-"][data-node-id]').first()
      await node.waitFor()
      await expect(node.getByTestId('status-badge')).toHaveText(/done/i, { timeout: 20000 })
      await node.locator('[data-preview-kind="spectrum-thumb"] canvas').waitFor()

      // The synthetic KCWI cube: white-light thumbnail, then the viewer's WCS readout.
      await revealSample(page, 'synthetic_kcwi_icubes.fits')
      await page.getByTestId('workspace-add').click()
      const cube = page.locator('[data-testid^="node-"][data-node-id]').nth(1)
      await cube.waitFor()
      await expect(cube.getByTestId('status-badge')).toHaveText(/done/i, { timeout: 30000 })
      await cube
        .locator('[data-preview-kind="cube-thumb"] [data-widget="image-view"] canvas')
        .waitFor()
      await cube.getByTestId('preview-expand').click()
      const viewer = page.getByTestId('viewer')
      await expect(viewer).toHaveAttribute('data-renderer', 'cube-thumb')
      const view = viewer.locator('[data-widget="image-view"]').first()
      await expect(view.getByTestId('image-limits')).toContainText('[')
      const canvas = view.locator('canvas')
      const box = await canvas.boundingBox()
      expect(box).not.toBeNull()
      await page.mouse.move(
        (box?.x ?? 0) + (box?.width ?? 0) / 2,
        (box?.y ?? 0) + (box?.height ?? 0) / 2,
      )
      // RA/Dec sexagesimal readout: hh:mm:ss.ss  ±dd:mm:ss.s
      await expect(view.getByTestId('image-readout')).toContainText(
        /\d\d:\d\d:\d\d\.\d+\s+[+-]\d\d:\d\d:\d\d\.\d/,
      )
      await page.getByTestId('viewer-close').click()
    } finally {
      await deleteWorkflow(request, id)
    }
  })
})
