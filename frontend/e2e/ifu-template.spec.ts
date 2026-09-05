/**
 * Phase 08 acceptance: the rbcodes ifu-cube-explorer template collapses a cube into images and
 * moment maps, the aperture editor draws an aperture on the white-light collapse and extracts a
 * spectrum through the node itself, and Apply pushes the apertures into the ds9 export.
 */
import type { APIRequestContext, Page } from '@playwright/test'
import { expect, test } from './fixtures'

import { deleteWorkflow, getWorkflow, openWorkflow } from './helpers'

const TEMPLATE_ID = 'rbcodes.ifu-cube-explorer'

interface Saved {
  doc: { id: string; name: string; nodes: Record<string, unknown> }
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

function nodeRoot(page: Page, nodeId: string) {
  return page.locator(`[data-testid="node-${nodeId}"]`)
}

test.describe('ifu-cube-explorer template', () => {
  test('collapses the cube, draws an aperture and exports the regions', async ({
    page,
    request,
  }) => {
    const templates = (await (await request.get('/api/templates')).json()) as { id: string }[]
    expect(templates.map((t) => t.id)).toContain(TEMPLATE_ID)
    test.setTimeout(180_000)
    const saved = await instantiate(request, 'E2E ifu')
    const id = saved.doc.id
    expect(saved.node_errors).toEqual({})
    try {
      await openWorkflow(page, id)
      for (const nodeId of ['load', 'white', 'nb', 'csub', 'extract', 'moments', 'snr', 'names']) {
        await expect(nodeRoot(page, nodeId).getByTestId('status-badge')).toHaveText(/done/i, {
          timeout: 90000,
        })
      }

      // The collapses render as images and the moment maps as a row of three tiles plus SNR.
      const whiteLight = nodeRoot(page, 'white').locator('[data-preview="image-thumb"]')
      await expect(whiteLight).toBeVisible({ timeout: 30000 })
      const maps = nodeRoot(page, 'moments').locator('[data-preview="moment-thumbs"]')
      await expect(maps).toBeVisible({ timeout: 30000 })
      await expect(maps).toHaveAttribute('data-maps', '4')
      await expect(maps.locator('[data-map="m1"]')).toBeVisible()
      await expect(maps).toContainText('km/s')

      // Three apertures were extracted into two source spectra (the third is the background).
      const stack = nodeRoot(page, 'extract').locator('[data-preview="spectrum-thumb"]')
      await expect(stack.first()).toBeVisible({ timeout: 30000 })

      // Open the aperture editor on the cube's white-light collapse.
      await nodeRoot(page, 'extract').getByTestId('node-editor').click()
      const editor = page.getByTestId('editor')
      await editor.waitFor()
      await expect(editor).toHaveAttribute('data-editor', 'aperture-editor')
      const surface = editor.getByTestId('editor-aperture')
      await expect(surface).toHaveAttribute('data-apertures', '3')
      await expect(surface.locator('[data-testid="aperture-row"]')).toHaveCount(3)
      await expect(surface.getByTestId('aperture-counts')).toContainText('2 source')
      // The overlay draws one shape per aperture over the collapse.
      await expect(surface.locator('[data-testid="aperture-shape"]')).toHaveCount(3)

      // The live extraction runs the node itself and draws the selected aperture's spectrum.
      await expect
        .poll(async () => (await surface.getByTestId('aperture-spectrum').textContent()) ?? '', {
          timeout: 30000,
        })
        .not.toContain('Extracting')

      // Draw a fourth aperture: drag across the image with the box tool.
      await surface.getByTestId('aperture-tool-box').click()
      const overlay = surface.getByTestId('aperture-overlay')
      const box = (await overlay.boundingBox())!
      await page.mouse.move(box.x + box.width * 0.25, box.y + box.height * 0.3)
      await page.mouse.down()
      await page.mouse.move(box.x + box.width * 0.4, box.y + box.height * 0.45, { steps: 8 })
      await page.mouse.up()
      await expect(surface).toHaveAttribute('data-apertures', '4', { timeout: 10000 })
      const label = surface.locator('[data-testid="aperture-label"]').last()
      await label.fill('e2e box')
      await label.press('Tab') // commits the field: the input is bound on `change`

      await surface.getByTestId('aperture-apply').click()
      await expect(editor).toHaveCount(0)

      // The node's parameters now hold the four apertures.
      await expect
        .poll(
          async () => {
            const doc = await getWorkflow(request, id)
            const params = (doc.nodes['extract'] as { params?: Record<string, unknown> }).params
            return (params?.['regions'] as unknown[] | undefined)?.length
          },
          { timeout: 15000 },
        )
        .toBe(4)

      // The export re-runs with them and writes a ds9 file naming the aperture drawn here.
      await expect(nodeRoot(page, 'reg').getByTestId('status-badge')).toHaveText(/done/i, {
        timeout: 60000,
      })
      await expect
        .poll(
          async () => {
            const response = await request.get(
              '/api/workspace/file?path=outputs%2Fifu-apertures.reg',
            )
            if (!response.ok()) return null
            const text = await response.text()
            return {
              apertures: text.split('\n').filter((line) => /^(circle|box|annulus)\(/.test(line))
                .length,
              named: text.includes('text={e2e box}'),
              sky: text.includes('icrs'),
            }
          },
          { timeout: 30000 },
        )
        .toEqual({ apertures: 4, named: true, sky: true })
    } finally {
      await deleteWorkflow(request, id)
    }
  })
})
