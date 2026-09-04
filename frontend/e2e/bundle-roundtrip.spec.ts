/**
 * Phase 11 acceptance: a workflow travels as a `.acw` and comes back intact, and Python that
 * arrives inside one does not run until it has been read.
 *
 * The round trip goes through the UI where it matters — the Share menu writes the bundle, the
 * quarantine banner and the trust dialog gate the code — and through the API where the UI has no
 * way to hand a browser a file it did not download.
 */
import { type Page, expect, test } from '@playwright/test'

import { E2E_TOKEN } from '../playwright.config'
import {
  type WorkflowDocLike,
  createWorkflow,
  deleteWorkflow,
  mathChain,
  openWorkflow,
  uniqueId,
} from './helpers'

/** A workflow whose only interesting node is a Python snippet nothing else has ever seen. */
function codeWorkflow(marker: string, id = uniqueId('e2e-code')): WorkflowDocLike {
  return {
    format: 'astro-canvas/workflow',
    version: 1,
    id,
    name: `Code ${id}`,
    nodes: {
      c: { type: 'core.math.constant', title: 'Input', pos: [80, 120], params: { value: 21.0 } },
      py: {
        type: 'core.code.python',
        title: 'Double it',
        pos: [420, 100],
        size: [340, 320],
        params: {
          // The marker keeps the hash unique per run: trust is per snippet, and the e2e
          // workspace outlives a run.
          source: `# ${marker}\nout = x * 2\n`,
          inputs: [{ name: 'x', type: 'astro.Float' }],
          outputs: [{ name: 'out', type: 'astro.Float' }],
        },
      },
    },
    edges: { e: { from: ['c', 'out'], to: ['py', 'x'] } },
  }
}

function nodeRoot(page: Page, nodeId: string) {
  return page.locator(`[data-testid="node-${nodeId}"]`)
}

async function valueOf(page: Page, nodeId: string): Promise<string> {
  const chip = nodeRoot(page, nodeId).locator('[data-preview="value-chip"]')
  await expect(chip).toBeVisible({ timeout: 30000 })
  return ((await chip.textContent()) ?? '').trim()
}

test.describe('bundles', () => {
  test('export from the Share menu writes a .acw into the workspace', async ({ page, request }) => {
    const doc = mathChain()
    await createWorkflow(request, doc)
    try {
      await openWorkflow(page, doc.id)
      await expect(nodeRoot(page, 'sum').getByTestId('status-badge')).toHaveText(/done/i, {
        timeout: 30000,
      })

      await page.getByTestId('share-menu').click()
      await page.getByTestId('share-export').click()
      await expect(page.getByTestId('bundle-dialog')).toBeVisible()
      await page.getByTestId('bundle-export').click()

      const result = page.getByTestId('bundle-result')
      await expect(result).toBeVisible({ timeout: 30000 })
      await expect(result).toContainText('.acw')
      await expect(result).toContainText(/\d+ output/)
      await page.getByTestId('bundle-close').click()
    } finally {
      await deleteWorkflow(request, doc.id)
    }
  })

  test('a bundle re-imports into a workflow that runs to the same numbers', async ({
    page,
    request,
  }) => {
    const doc = mathChain()
    await createWorkflow(request, doc)
    let imported: string | null = null
    try {
      await openWorkflow(page, doc.id)
      await expect(nodeRoot(page, 'sum').getByTestId('status-badge')).toHaveText(/done/i, {
        timeout: 30000,
      })
      const before = await valueOf(page, 'sum')

      const manifest = await (
        await request.post('/api/bundles/export', { data: { workflow_id: doc.id } })
      ).json()
      expect(manifest.path).toContain('.acw')

      const download = await request.get(
        `/api/bundles/download?path=${encodeURIComponent(manifest.path)}`,
      )
      expect(download.status()).toBe(200)
      const payload = await download.body()

      const response = await request.post('/api/bundles/import', {
        multipart: {
          file: { name: 'roundtrip.acw', mimeType: 'application/zip', buffer: payload },
        },
      })
      expect(response.status()).toBe(201)
      const result = await response.json()
      imported = result.workflow_id as string

      // A fresh id, the same node ids (layout refs address those), nothing missing.
      expect(imported).not.toBe(doc.id)
      expect(result.missing_packs).toEqual({})
      expect(result.layout_errors).toEqual([])
      expect(result.quarantined).toBe(false)

      await openWorkflow(page, imported)
      await expect(nodeRoot(page, 'sum').getByTestId('status-badge')).toHaveText(/done/i, {
        timeout: 30000,
      })
      expect(await valueOf(page, 'sum')).toBe(before)
    } finally {
      await deleteWorkflow(request, doc.id)
      if (imported) await deleteWorkflow(request, imported)
    }
  })

  test('a file that is not a bundle is refused', async ({ request }) => {
    // Hostile archives (traversal, zip bombs, pickles) are covered exhaustively against the
    // import endpoint in `backend/tests/manager/test_bundle_security.py`; here the point is that
    // the endpoint refuses rather than half-importing.
    const response = await request.post('/api/bundles/import', {
      multipart: {
        file: {
          name: 'not-a-bundle.acw',
          mimeType: 'application/zip',
          buffer: Buffer.from('PK definitely not a zip', 'utf-8'),
        },
      },
    })
    expect(response.status()).toBe(400)
    expect(await response.text()).toContain('detail')
  })

  test('imported Python is quarantined until it is read, then runs', async ({ page, request }) => {
    const marker = uniqueId('snippet')
    const source = codeWorkflow(marker)
    await createWorkflow(request, source)
    let imported: string | null = null
    try {
      // Locally authored code is trusted, so it runs straight away.
      await openWorkflow(page, source.id)
      await expect(nodeRoot(page, 'py').getByTestId('status-badge')).toHaveText(/done/i, {
        timeout: 30000,
      })
      expect(await valueOf(page, 'py')).toContain('42')
      await expect(page.getByTestId('quarantine-banner')).toHaveCount(0)

      // Re-import the same document under a snippet this workspace has not decided on: a fresh
      // marker makes the hash new, which is exactly what a bundle from someone else looks like.
      const stranger = codeWorkflow(uniqueId('stranger'), uniqueId('e2e-import'))
      const response = await request.post('/api/bundles/import', {
        multipart: {
          file: {
            name: 'stranger.acw',
            mimeType: 'application/json',
            buffer: Buffer.from(JSON.stringify(stranger), 'utf-8'),
          },
        },
      })
      expect(response.status()).toBe(201)
      const result = await response.json()
      imported = result.workflow_id as string
      expect(result.quarantined).toBe(true)

      await openWorkflow(page, imported)
      const banner = page.getByTestId('quarantine-banner')
      await expect(banner).toBeVisible({ timeout: 20000 })
      // The code node itself says why, and produced nothing.
      await expect(nodeRoot(page, 'py')).toContainText(/review and trust/i)
      await expect(nodeRoot(page, 'py').locator('[data-preview="value-chip"]')).toHaveCount(0)

      await page.getByTestId('quarantine-review').click()
      const dialog = page.getByTestId('trust-dialog')
      await expect(dialog).toBeVisible()
      // The snippet is shown in full before any decision is asked for.
      await expect(page.getByTestId('trust-source-py')).toContainText('out = x * 2')
      await expect(page.getByTestId('trust-snippet-py')).toHaveAttribute('data-decision', 'none')

      await page.getByTestId('trust-accept-py').click()
      await expect(page.getByTestId('trust-snippet-py')).toHaveAttribute(
        'data-decision',
        'trusted',
        { timeout: 20000 },
      )
      await page.getByTestId('trust-close').click()

      await expect(banner).toHaveCount(0, { timeout: 20000 })
      await page.getByTestId('run').click()
      await expect(nodeRoot(page, 'py').getByTestId('status-badge')).toHaveText(/done/i, {
        timeout: 30000,
      })
      expect(await valueOf(page, 'py')).toContain('42')
    } finally {
      await deleteWorkflow(request, source.id)
      if (imported) await deleteWorkflow(request, imported)
    }
  })

  test('editing a trusted snippet quarantines it again', async ({ page, request }) => {
    const doc = codeWorkflow(uniqueId('editable'))
    await createWorkflow(request, doc)
    try {
      await openWorkflow(page, doc.id)
      await expect(nodeRoot(page, 'py').getByTestId('status-badge')).toHaveText(/done/i, {
        timeout: 30000,
      })

      // Mark it as arriving from outside, then change the snippet: a different snippet is a
      // different decision, so the gate closes.
      const edited = { ...doc }
      edited.meta = { ...(doc.meta ?? {}), quarantine: true }
      edited.nodes.py = {
        ...doc.nodes.py,
        params: {
          ...(doc.nodes.py as { params: Record<string, unknown> }).params,
          source: `# edited ${uniqueId('after')}\nout = x * 3\n`,
        },
      }
      const saved = await request.put(`/api/workflows/${encodeURIComponent(doc.id)}`, {
        data: edited,
      })
      expect(saved.status()).toBe(200)
      const body = await saved.json()
      expect(body.node_errors.py?.[0]?.code).toBe('quarantined')

      await page.goto(`/w/${encodeURIComponent(doc.id)}?token=${E2E_TOKEN}`)
      await page.getByTestId('canvas').waitFor()
      await expect(page.getByTestId('quarantine-banner')).toBeVisible({ timeout: 20000 })
    } finally {
      await deleteWorkflow(request, doc.id)
    }
  })
})
