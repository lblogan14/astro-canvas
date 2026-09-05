/**
 * Phase 09 acceptance: collapsing four nodes into a subgraph keeps the graph running with the
 * same outputs, the body opens behind a breadcrumb, expanding restores the positions, and
 * Ctrl+Shift+L tidies the canvas.
 */
import type { Page } from '@playwright/test'
import { expect, test } from './fixtures'

import { createWorkflow, deleteWorkflow, getWorkflow, mathChain, openWorkflow } from './helpers'

function nodeRoot(page: Page, nodeId: string) {
  return page.locator(`[data-testid="node-${nodeId}"]`)
}

async function valueOf(page: Page, nodeId: string): Promise<string> {
  const chip = nodeRoot(page, nodeId).locator('[data-preview="value-chip"]')
  await expect(chip).toBeVisible({ timeout: 30000 })
  return ((await chip.textContent()) ?? '').trim()
}

test.describe('subgraphs', () => {
  test('collapse keeps the result, the body opens, and expanding restores positions', async ({
    page,
    request,
  }) => {
    const doc = mathChain()
    await createWorkflow(request, doc)
    try {
      await openWorkflow(page, doc.id)
      await expect(nodeRoot(page, 'sum').getByTestId('status-badge')).toHaveText(/done/i, {
        timeout: 30000,
      })
      const before = await valueOf(page, 'sum')
      const positions = (await getWorkflow(request, doc.id)).nodes

      // Collapse the whole chain (c, sq, sum, note) into one subgraph.
      await page.getByTestId('canvas').focus()
      await page.keyboard.press('Control+a')
      await page.keyboard.press('Control+Shift+C')

      const instance = page.locator('[data-testid^="node-"][data-subgraph]')
      await expect(instance).toHaveCount(1)
      await expect(nodeRoot(page, 'sum')).toHaveCount(0)

      // The engine runs the inlined body and reports its nodes as `<instance>/<inner>`.
      await expect
        .poll(
          async () => Object.keys((await getWorkflow(request, doc.id)).subgraphs ?? {}).length,
          {
            timeout: 20000,
          },
        )
        .toBe(1)
      const saved = await getWorkflow(request, doc.id)
      const instanceId = Object.keys(saved.nodes).find((id) =>
        String((saved.nodes[id] as { type: string }).type).startsWith('subgraph:'),
      ) as string
      await expect
        .poll(
          async () => {
            const status = (await (
              await request.get(`/api/workflows/${doc.id}/status`)
            ).json()) as { nodes: Record<string, { state: string }> }
            return status.nodes[`${instanceId}/sum`]?.state
          },
          { timeout: 30000 },
        )
        .toBe('done')

      // Double-clicking opens the body behind a breadcrumb; the root is one click away.
      await instance.dblclick()
      await expect(page.getByTestId('subgraph-breadcrumb')).toHaveAttribute('data-depth', '1')
      await expect(nodeRoot(page, 'sum')).toBeVisible()
      expect(await valueOf(page, 'sum')).toBe(before)
      await page.getByTestId('breadcrumb-root').click()
      await expect(page.getByTestId('subgraph-breadcrumb')).toHaveCount(0)

      // Expanding puts every node back where it was.
      await instance.click()
      await page.keyboard.press('Control+Shift+E')
      await expect(nodeRoot(page, 'sum')).toBeVisible()
      await expect(page.locator('[data-testid^="node-"][data-subgraph]')).toHaveCount(0)
      await expect
        .poll(async () => {
          const restored = await getWorkflow(request, doc.id)
          return restored.nodes['sum']?.pos
        })
        .toEqual(positions['sum']?.pos)
      expect(await valueOf(page, 'sum')).toBe(before)
    } finally {
      await deleteWorkflow(request, doc.id)
    }
  })

  test('auto-layout tidies the graph left to right', async ({ page, request }) => {
    const doc = mathChain()
    doc.nodes['c'] = { ...doc.nodes['c'], pos: [900, 700] }
    doc.nodes['sq'] = { ...doc.nodes['sq'], pos: [200, 40] }
    await createWorkflow(request, doc)
    try {
      await openWorkflow(page, doc.id)
      await expect(nodeRoot(page, 'sum')).toBeVisible()
      await page.getByTestId('canvas').focus()
      await page.keyboard.press('Control+Shift+L')
      await expect
        .poll(
          async () => {
            const laid = await getWorkflow(request, doc.id)
            const c = (laid.nodes['c']?.pos as [number, number] | undefined)?.[0] ?? 0
            const sq = (laid.nodes['sq']?.pos as [number, number] | undefined)?.[0] ?? 0
            const sum = (laid.nodes['sum']?.pos as [number, number] | undefined)?.[0] ?? 0
            return c < sq && sq < sum
          },
          { timeout: 20000 },
        )
        .toBe(true)
    } finally {
      await deleteWorkflow(request, doc.id)
    }
  })
})
