/**
 * Phase 06 acceptance: the rbcodes redshift-finder template runs to a Redshift, the z-accept
 * editor lists the candidates of three scans with the line list overlaid on the spectrum, and
 * Apply writes `accepted` so Set Redshift follows the chosen candidate. The expensive PCA node
 * runs in the process pool on demand and reports progress.
 */
import { expect, test, type APIRequestContext, type Page } from '@playwright/test'

import { deleteWorkflow, getWorkflow, openWorkflow } from './helpers'

const TEMPLATE_ID = 'rbcodes.redshift-finder'
const GALAXY_Z = 0.00586

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

async function readZ(page: Page, nodeId: string): Promise<number> {
  const cell = nodeRoot(page, nodeId).locator('[data-widget="kv-tile"] dd[data-key="z"]')
  await expect(cell).toBeVisible({ timeout: 30000 })
  const text = (await cell.textContent()) ?? ''
  const value = Number.parseFloat(text.replace(/[^0-9eE+.-]/g, ''))
  expect(Number.isFinite(value)).toBe(true)
  return value
}

test.describe('redshift-finder template', () => {
  test('scans recover the galaxy redshift and the z-accept editor writes the accepted candidate', async ({
    page,
    request,
  }) => {
    const templates = (await (await request.get('/api/templates')).json()) as { id: string }[]
    expect(templates.map((t) => t.id)).toContain(TEMPLATE_ID)
    test.setTimeout(180_000)
    const saved = await instantiate(request, 'E2E redshift')
    const id = saved.doc.id
    expect(saved.node_errors).toEqual({})
    try {
      await openWorkflow(page, id)
      for (const nodeId of [
        'pf_gal',
        'ls_gal',
        'tpl_gal',
        'rank_gal',
        'zshift_gal',
        'pf_qso',
        'rank_qso',
      ]) {
        await expect(nodeRoot(page, nodeId).getByTestId('status-badge')).toHaveText(/done/i, {
          timeout: 90000,
        })
      }
      // The picket fence preview shows a curve with candidate markers and the best z.
      const curve = nodeRoot(page, 'pf_gal').locator('[data-preview="zfind-curve"]')
      await expect(curve).toBeVisible({ timeout: 30000 })
      await expect(curve.locator('[data-marker]').first()).toBeAttached()
      await expect(curve.getByTestId('zfind-best')).toContainText(/z = 0\.005/)
      // The accepted redshift (best of the first scan) drives Set Redshift.
      const before = await readZ(page, 'rank_gal')
      expect(Math.abs(before - GALAXY_Z)).toBeLessThan(0.002)
      const table = nodeRoot(page, 'rank_gal').locator('[data-preview="candidates-table"]')
      await expect(table).toHaveAttribute('data-accepted', '0')

      // Open the z-accept editor: three scans, their candidates, and lines on the spectrum.
      await nodeRoot(page, 'rank_gal').getByTestId('node-editor').click()
      const editor = page.getByTestId('editor')
      await editor.waitFor()
      await expect(editor).toHaveAttribute('data-editor', 'z-accept')
      await expect(editor.locator('[data-testid="zaccept-source"]')).toHaveCount(3, {
        timeout: 20000,
      })
      const rows = editor.locator('[data-testid="zaccept-candidate"]')
      await expect(rows.first()).toBeVisible({ timeout: 20000 })
      const count = await rows.count()
      expect(count).toBeGreaterThan(10)
      await expect(editor.getByTestId('zaccept-selected')).toHaveAttribute('data-index', '0')
      await expect(editor.getByTestId('zaccept-linelist')).toHaveValue('zfind_galaxy')
      // At the galaxy redshift the whole zfind_galaxy list falls on the SDSS grid.
      await expect
        .poll(
          async () =>
            Number(await editor.getByTestId('zaccept-spectrum').getAttribute('data-lines')),
          {
            timeout: 15000,
          },
        )
        .toBeGreaterThan(5)
      // Pick the template scan's best candidate (source 2) and Apply.
      const templateRow = editor
        .locator('[data-testid="zaccept-candidate"][data-source="2"]')
        .first()
      const chosen = Number(await templateRow.getAttribute('data-index'))
      await templateRow.click()
      await expect(editor.getByTestId('zaccept-selected')).toHaveAttribute(
        'data-index',
        String(chosen),
      )
      await expect(editor.getByTestId('zaccept-curve')).toHaveAttribute('data-source', '2')
      await editor.getByTestId('editor-apply').click()
      await expect(editor).toHaveCount(0)
      await expect
        .poll(
          async () => {
            const response = await request.get(`/api/workflows/${encodeURIComponent(id)}`)
            const doc = (await response.json()) as {
              nodes: Record<string, { params?: Record<string, unknown> }>
            }
            return doc.nodes['rank_gal']?.params?.['accepted']
          },
          { timeout: 15000 },
        )
        .toBe(chosen)
      await expect(table).toHaveAttribute('data-accepted', String(chosen), { timeout: 30000 })
      await expect(nodeRoot(page, 'zshift_gal').getByTestId('status-badge')).toHaveText(/done/i, {
        timeout: 60000,
      })
      const after = await readZ(page, 'rank_gal')
      console.log(`accepted z before ${before}, after ${after} (row ${chosen})`)
      expect(after).not.toBe(before)
      expect(Math.abs(after - GALAXY_Z)).toBeLessThan(0.005)
    } finally {
      await deleteWorkflow(request, id)
    }
  })

  test('the expensive PCA search runs in the process pool with progress', async ({
    page,
    request,
  }) => {
    test.setTimeout(180_000)
    const saved = await instantiate(request, 'E2E redshift pca')
    const id = saved.doc.id
    try {
      await openWorkflow(page, id)
      // The e2e workspace (and its content-addressed cache) persists between runs: give the
      // PCA node a grid size no earlier run used so the scan really executes in the pool.
      const doc = await getWorkflow(request, id)
      const pcaNode = doc.nodes['pca_gal'] as { params?: Record<string, unknown> }
      pcaNode.params = { ...pcaNode.params, n_steps: 700 + (Date.now() % 250) }
      const put = await request.put(`/api/workflows/${encodeURIComponent(id)}`, { data: doc })
      expect(put.ok()).toBe(true)
      const pca = nodeRoot(page, 'pca_gal')
      await expect(pca.getByTestId('status-badge')).toHaveText(/stale|idle|dirty/i, {
        timeout: 30000,
      })
      // Select the node: its toolbar (rendered in Vue Flow's toolbar layer) shows "Run to here".
      await pca.getByTestId('status-badge').click()
      const runHere = page.getByTestId('node-run')
      await expect(runHere).toBeVisible({ timeout: 10000 })
      await runHere.click()
      await expect(pca.getByTestId('status-badge')).toHaveText(/running|queued|done/i, {
        timeout: 30000,
      })
      await expect(pca.getByTestId('status-badge')).toHaveText(/done/i, { timeout: 120000 })
      const curve = pca.locator('[data-preview="zfind-curve"]')
      await expect(curve.getByTestId('zfind-best')).toContainText(/z = 0\.00/, { timeout: 30000 })
    } finally {
      await deleteWorkflow(request, id)
    }
  })
})
