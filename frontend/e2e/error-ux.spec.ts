/**
 * Error UX end to end (phase 13, scope item 4).
 *
 * What the unit tests cannot show: that a node failure reaches the canvas *with its hint*, that
 * the banner really appears when the network goes away and really clears when it comes back, and
 * that a malformed document is refused rather than stored.
 *
 * The other two states in `ShellNotices` are covered where they can actually be produced: the
 * recovery of an unreadable document in `backend/tests/server/test_error_ux.py` (only something
 * inside the server can corrupt a stored row) and the banners themselves in
 * `src/app/__tests__/ShellNotices.spec.ts`.
 */
import { expect, test } from './fixtures'

import {
  type WorkflowDocLike,
  createWorkflow,
  deleteWorkflow,
  mathChain,
  openWorkflow,
  uniqueId,
} from './helpers'

/** A loader pointed at a file that is not there: the commonest real failure. */
function missingFile(id = uniqueId('e2e-missing')): WorkflowDocLike {
  return {
    format: 'astro-canvas/workflow',
    version: 1,
    id,
    name: `Missing file ${id}`,
    nodes: {
      load: {
        type: 'core.io.load_spectrum',
        title: 'Load',
        pos: [80, 80],
        params: { path: 'samples/rbcodes/definitely-not-here.fits' },
      },
    },
    edges: {},
  }
}

test.describe('error UX', () => {
  test('a node failure shows the message and the hint, on the node and in the drawer', async ({
    page,
    request,
  }) => {
    const doc = missingFile()
    await createWorkflow(request, doc)
    try {
      await openWorkflow(page, doc.id)
      const node = page.getByTestId('node-load')
      await expect(node.getByTestId('status-badge')).toHaveText(/error/i, { timeout: 60000 })

      // The alert button on the node opens the exception's own words and what to do about them.
      await node.getByTestId('error-trigger').click()
      const detail = page.getByTestId('error-detail')
      await expect(detail).toContainText(/FileNotFoundError|no such file/i)
      await expect(detail).toContainText('Workspace panel')
      await page.keyboard.press('Escape')

      await page.getByTestId('toggle-drawer').click()
      const drawer = page.getByTestId('drawer')
      await drawer.locator('[data-tab="errors"]').click()
      await expect(drawer).toContainText('Workspace panel')
    } finally {
      await deleteWorkflow(request, doc.id)
    }
  })

  test('losing the event socket raises the banner, and getting it back clears it', async ({
    page,
    request,
  }) => {
    const doc = mathChain()
    await createWorkflow(request, doc)
    try {
      await openWorkflow(page, doc.id)
      await expect(page.getByTestId('shell-notices')).toHaveCount(0)

      // `setOffline` does not drop an established socket, and a page cannot be reloaded with the
      // network off, so the socket is what goes away: while `blocked`, every handshake is closed
      // on arrival, which is what an event socket the server is not answering looks like. The
      // route stays installed either way and proxies to the real server once it is lifted --
      // `unrouteAll` does not remove a WebSocket route.
      let blocked = true
      await page.routeWebSocket('**/ws*', (ws) => {
        if (blocked) ws.close()
        else ws.connectToServer()
      })
      await page.reload()
      await page.getByTestId('canvas').waitFor()

      const notice = page.getByTestId('notice-offline')
      await expect(notice).toBeVisible({ timeout: 30000 })
      // The socket says it is retrying rather than simply dead.
      await expect(notice).toHaveAttribute('data-reconnecting', 'true', { timeout: 30000 })

      // With the socket reachable again, Retry reconnects without waiting out the back-off.
      blocked = false
      await page.getByTestId('notice-retry').click()
      await expect(page.getByTestId('ws-status')).toHaveAttribute('data-status', 'open', {
        timeout: 30000,
      })
      await expect(page.getByTestId('notice-offline')).toHaveCount(0)

      // And the canvas is live again: an edit still propagates.
      const value = page.getByTestId('node-c').locator('[data-param="value"] input')
      await value.fill('5')
      await value.press('Enter')
      await expect(page.getByTestId('node-sum').locator('[data-summary-port="out"]')).toContainText(
        '31',
      )
    } finally {
      await deleteWorkflow(request, doc.id)
    }
  })

  test('a malformed document is refused rather than stored', async ({ request }) => {
    const doc = mathChain()
    await createWorkflow(request, doc)
    try {
      const broken = { ...doc, nodes: { c: { type: 42 } } }
      const rejected = await request.put(`/api/workflows/${encodeURIComponent(doc.id)}`, {
        data: broken,
      })
      expect(rejected.status()).toBe(422)
      // And the stored document is untouched.
      const stored = await (
        await request.get(`/api/workflows/${encodeURIComponent(doc.id)}`)
      ).json()
      expect(stored.nodes.c.type).toBe('core.math.constant')
    } finally {
      await deleteWorkflow(request, doc.id)
    }
  })
})
