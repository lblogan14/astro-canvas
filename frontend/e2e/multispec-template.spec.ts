/**
 * Phase 07 acceptance: the rbcodes multi-spectrum-viewer template stacks three SDSS spectra,
 * the viewer editor overlays a line list at a redshift and turns a click into an identified
 * line, and Apply pushes both catalogues into the export node's file.
 */
import { expect, test, type APIRequestContext, type Page } from '@playwright/test'

import { deleteWorkflow, getWorkflow, openWorkflow } from './helpers'

const TEMPLATE_ID = 'rbcodes.multi-spectrum-viewer'
const MGII_Z = 1.3855

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

test.describe('multi-spectrum-viewer template', () => {
  test('stacks three spectra, identifies a line in the editor and exports the catalogues', async ({
    page,
    request,
  }) => {
    const templates = (await (await request.get('/api/templates')).json()) as { id: string }[]
    expect(templates.map((t) => t.id)).toContain(TEMPLATE_ID)
    test.setTimeout(180_000)
    const saved = await instantiate(request, 'E2E multispec')
    const id = saved.doc.id
    expect(saved.node_errors).toEqual({})
    try {
      await openWorkflow(page, id)
      for (const nodeId of ['stack', 'absorbers', 'catalog', 'viewer', 'export', 'vstack', 'fit']) {
        await expect(nodeRoot(page, nodeId).getByTestId('status-badge')).toHaveText(/done/i, {
          timeout: 90000,
        })
      }
      // The viewer's inline preview shows the stack with the pre-identified MgII doublet.
      const thumb = nodeRoot(page, 'viewer').locator('[data-preview="multispec-thumb"]')
      await expect(thumb).toBeVisible({ timeout: 30000 })
      await expect(thumb).toHaveAttribute('data-panels', '3')
      await expect(thumb).toHaveAttribute('data-lines', '2')
      await expect(thumb.getByTestId('multispec-thumb-z')).toContainText('1.385500')

      // Open the editor: three stacked panels sharing one wavelength axis.
      await nodeRoot(page, 'viewer').getByTestId('node-editor').click()
      const editor = page.getByTestId('editor')
      await editor.waitFor()
      await expect(editor).toHaveAttribute('data-editor', 'multispec-viewer')
      const panels = editor.locator('[data-testid="multispec-panel"]')
      await expect(panels).toHaveCount(3, { timeout: 30000 })
      await expect(editor.getByTestId('multispec-z')).toHaveValue(String(MGII_Z))
      await expect(editor.getByTestId('multispec-linelist')).toHaveValue('LLS')
      // The seeded absorber systems and the pre-identified doublet are listed.
      await expect(editor.getByTestId('multispec-absorbers')).toHaveAttribute('data-count', '3')
      await expect(editor.getByTestId('multispec-lines')).toHaveAttribute('data-count', '2')
      // The LLS list arrives through preview.compute and lands on the panels as markers.
      await expect
        .poll(async () => Number(await panels.first().getAttribute('data-markers')), {
          timeout: 20000,
        })
        .toBeGreaterThan(2)

      // Toggle two more line lists: the marker count changes with the overlay.
      const before = Number(await panels.first().getAttribute('data-markers'))
      await editor.getByTestId('multispec-linelist').selectOption('DLA')
      await expect
        .poll(async () => Number(await panels.first().getAttribute('data-markers')), {
          timeout: 20000,
        })
        .not.toBe(before)
      await editor.getByTestId('multispec-linelist').selectOption('LLS')

      // Click a feature on the first panel: the nearest transition is appended.
      const box = (await panels.first().boundingBox())!
      await page.mouse.click(box.x + box.width * 0.62, box.y + box.height * 0.5)
      await expect(editor.getByTestId('multispec-lines')).toHaveAttribute('data-count', '3', {
        timeout: 15000,
      })
      const identified = await editor.locator('[data-testid="multispec-line"]').last().textContent()
      console.log(`identified ${identified?.trim()}`)

      // Add an absorber at the current redshift and apply.
      await editor.getByTestId('multispec-add-absorber').click()
      await expect(editor.getByTestId('multispec-absorbers')).toHaveAttribute('data-count', '4')
      await editor.getByTestId('editor-apply').click()
      await expect(editor).toHaveCount(0)

      // The node's parameters now hold the edited catalogues.
      await expect
        .poll(
          async () => {
            const doc = await getWorkflow(request, id)
            const params = (doc.nodes['viewer'] as { params?: Record<string, unknown> }).params
            return (params?.['identifications'] as unknown[] | undefined)?.length
          },
          { timeout: 15000 },
        )
        .toBe(3)

      // Export re-runs and writes the MultispecViewer document with the new rows.
      await expect(nodeRoot(page, 'export').getByTestId('status-badge')).toHaveText(/done/i, {
        timeout: 60000,
      })
      await expect
        .poll(
          async () => {
            const response = await request.get(
              '/api/workspace/file?path=outputs%2Fmultispec-lines.json',
            )
            if (!response.ok()) return null
            const document = JSON.parse(await response.text()) as {
              line_list: unknown[]
              absorbers: unknown[]
              metadata: { application_name: string }
            }
            return {
              lines: document.line_list.length,
              absorbers: document.absorbers.length,
              app: document.metadata.application_name,
            }
          },
          { timeout: 30000 },
        )
        .toEqual({ lines: 3, absorbers: 4, app: 'MultispecViewer' })
    } finally {
      await deleteWorkflow(request, id)
    }
  })
})
