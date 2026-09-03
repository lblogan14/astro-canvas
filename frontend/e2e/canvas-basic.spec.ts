import { expect, test } from '@playwright/test'

import {
  comparable,
  createWorkflow,
  deleteWorkflow,
  getWorkflow,
  mathChain,
  openWorkflow,
  uniqueId,
} from './helpers'

test.describe('canvas basics', () => {
  test('adds two nodes, connects them, runs, and shows status badges', async ({
    page,
    request,
  }) => {
    const id = uniqueId('e2e-basic')
    await createWorkflow(request, {
      format: 'astro-canvas/workflow',
      version: 1,
      id,
      name: 'Basic',
      nodes: {},
      edges: {},
    })
    try {
      await openWorkflow(page, id)

      // Add a constant and an expression through the library (double-click adds at the centre).
      const library = page.getByTestId('node-library')
      await library.getByTestId('library-search').fill('constant')
      await library.locator('[data-node-type="core.math.constant"] button').first().dblclick()
      await expect(page.locator('.ac-node')).toHaveCount(1)
      // Set the constant to 5 while it is the only node on the canvas.
      const value = page.locator('.ac-node [data-param="value"] input')
      await value.fill('5')
      await value.press('Enter')
      await library.getByTestId('library-search').fill('expression')
      await library.locator('[data-node-type="core.math.expr"] button').first().dblclick()
      await expect(page.locator('.ac-node')).toHaveCount(2)

      // Both nodes appear at the viewport centre; move the expression below the constant so
      // the handles do not overlap (and it stays clear of the inspector on the right).
      const constant = page
        .locator('.vue-flow__node[data-id]')
        .filter({ has: page.locator('[title="core.math.constant"]') })
      const expr = page
        .locator('.vue-flow__node[data-id]')
        .filter({ has: page.locator('[title="core.math.expr"]') })
      const header = expr.locator('header')
      const headerBox = (await header.boundingBox())!
      await header.hover()
      await page.mouse.down()
      await page.mouse.move(headerBox.x + headerBox.width / 2 + 40, headerBox.y + 240, { steps: 8 })
      await page.mouse.up()

      // Link the expression's `x` param so it becomes an input port, then connect out → x.
      await expr.locator('[data-param="x"] [data-link-toggle]').click()
      const source = constant.locator('.vue-flow__handle.source')
      const target = expr.locator('.vue-flow__handle.target').first()
      await expect(target).toBeVisible()
      const s = (await source.boundingBox())!
      const d = (await target.boundingBox())!
      await page.mouse.move(s.x + s.width / 2, s.y + s.height / 2)
      await page.mouse.down()
      await page.mouse.move(d.x + d.width / 2, d.y + d.height / 2, { steps: 12 })
      await page.mouse.up()
      await expect(page.locator('.vue-flow__edge')).toHaveCount(1)

      // The expression is `x`, so the chain evaluates to 5. Cheap nodes auto-run after the
      // autosave; explicit Run also works.
      await page.getByTestId('run').click()
      await expect(constant.getByTestId('status-badge')).toHaveText(/done/i)
      await expect(expr.getByTestId('status-badge')).toHaveText(/done/i)
      await expect(expr.locator('[data-summary-port="out"]')).toContainText('5')

      // The document persisted with the edge.
      await expect
        .poll(async () => Object.keys((await getWorkflow(request, id)).edges).length)
        .toBe(1)
    } finally {
      await deleteWorkflow(request, id)
    }
  })

  test('loads a fixture, refuses an invalid connection, and survives a reload unchanged', async ({
    page,
    request,
  }) => {
    const doc = mathChain()
    await createWorkflow(request, doc)
    try {
      await openWorkflow(page, doc.id)
      await expect(page.locator('.ac-node')).toHaveCount(4)
      await expect(page.locator('.vue-flow__edge')).toHaveCount(3)
      await expect(page.getByTestId('node-sum').getByTestId('status-badge')).toHaveText(/done/i)
      await expect(page.getByTestId('node-sum').locator('[data-summary-port="out"]')).toContainText(
        '7',
      )

      // `sq.x` is already fed by `c`; dragging `sum.out` onto it must be refused with a message.
      const sumOut = page.locator('.vue-flow__node[data-id="sum"] .vue-flow__handle.source')
      const sqX = page.locator('.vue-flow__node[data-id="sq"] .vue-flow__handle.target')
      const s = (await sumOut.boundingBox())!
      const d = (await sqX.boundingBox())!
      await page.mouse.move(s.x + s.width / 2, s.y + s.height / 2)
      await page.mouse.down()
      await page.mouse.move(d.x + d.width / 2, d.y + d.height / 2, { steps: 12 })
      await page.mouse.up()
      await expect(page.locator('.vue-flow__edge')).toHaveCount(3)
      await expect(page.getByTestId('toast')).toBeVisible()

      // Disconnect an edge, wait for the save, then reload: the stored doc round-trips.
      // Edges are thin SVG paths: a synthetic click on the edge group selects it reliably.
      await page.locator('.vue-flow__edge[data-id="e3"]').dispatchEvent('click')
      await expect(page.locator('.vue-flow__edge[data-id="e3"]')).toHaveClass(/selected/)
      await page.getByTestId('canvas').focus()
      await page.keyboard.press('Delete')
      await expect(page.locator('.vue-flow__edge')).toHaveCount(2)
      await expect(page.getByTestId('save-state')).toHaveAttribute('data-state', 'saved')
      const before = await getWorkflow(request, doc.id)
      expect(Object.keys(before.edges)).toEqual(['e1', 'e2'])
      await page.reload()
      await page.getByTestId('canvas').waitFor()
      await expect(page.locator('.vue-flow__edge')).toHaveCount(2)
      // Give a spurious autosave (1 s debounce) the chance to fire before comparing.
      // eslint-disable-next-line playwright/no-wait-for-timeout -- asserting that nothing happens
      await page.waitForTimeout(1500)
      await expect(page.getByTestId('save-state')).toHaveAttribute('data-state', 'clean')
      const after = await getWorkflow(request, doc.id)
      expect(comparable(after)).toEqual(comparable(before))
    } finally {
      await deleteWorkflow(request, doc.id)
    }
  })

  test('param edits on cheap nodes propagate over the WebSocket without pressing Run', async ({
    page,
    request,
  }) => {
    const doc = mathChain()
    await createWorkflow(request, doc)
    try {
      await openWorkflow(page, doc.id)
      const sum = page.getByTestId('node-sum')
      await expect(sum.locator('[data-summary-port="out"]')).toContainText('7')
      const value = page.getByTestId('node-c').locator('[data-param="value"] input')
      await value.fill('3')
      await value.press('Enter')
      // 3² + 3 + 1 = 13, computed by the engine after the debounced autosave.
      await expect(sum.locator('[data-summary-port="out"]')).toContainText('13')
      await expect(sum.getByTestId('status-badge')).toHaveText(/done/i)
      // Undo restores the value and re-runs.
      await page.getByTestId('undo').click()
      await expect(sum.locator('[data-summary-port="out"]')).toContainText('7')
    } finally {
      await deleteWorkflow(request, doc.id)
    }
  })

  test('copy/paste keeps internal edges and groups are undoable', async ({ page, request }) => {
    const doc = mathChain()
    await createWorkflow(request, doc)
    try {
      await openWorkflow(page, doc.id)
      await page.getByTestId('canvas').focus()
      await page.keyboard.press('Control+a')
      await page.keyboard.press('Control+c')
      await page.keyboard.press('Control+v')
      await expect(page.locator('.ac-node')).toHaveCount(8)
      await expect(page.locator('.vue-flow__edge')).toHaveCount(6)
      await page.keyboard.press('Control+g')
      await expect(page.getByTestId('group')).toHaveCount(1)
      await page.getByTestId('undo').click()
      await expect(page.getByTestId('group')).toHaveCount(0)
      await page.getByTestId('undo').click()
      await expect(page.locator('.ac-node')).toHaveCount(4)
      await expect(page.locator('.vue-flow__edge')).toHaveCount(3)
    } finally {
      await deleteWorkflow(request, doc.id)
    }
  })
})
