/**
 * Accessibility (phase 13, scope item 3): axe-core over the surfaces a user cannot avoid.
 *
 * The gate, the exclusions and the animation settling live in `a11y.ts`, because the login page
 * is audited from the `users` project (`users-auth.spec.ts`) and shares them.
 */
import type { APIRequestContext, Page } from '@playwright/test'
import { expect, test } from './fixtures'

import { audit } from './a11y'
import {
  type WorkflowDocLike,
  createWorkflow,
  deleteWorkflow,
  mathChain,
  openWorkflow,
  uniqueId,
} from './helpers'

const ABSORPTION = 'rbcodes.absorption-line-measurement'

/** Open a fresh math chain and wait until the shell is live. */
async function shell(page: Page, request: APIRequestContext): Promise<WorkflowDocLike> {
  const doc = mathChain()
  await createWorkflow(request, doc)
  await openWorkflow(page, doc.id)
  // Audit the shell in its working state, with the toolbar live.
  await expect(page.getByTestId('run')).toBeEnabled()
  return doc
}

async function instantiate(request: APIRequestContext, template: string): Promise<string> {
  const response = await request.post(
    `/api/templates/${encodeURIComponent(template)}/instantiate`,
    { data: { name: `a11y ${uniqueId('t')}` } },
  )
  expect(response.status()).toBe(201)
  return ((await response.json()) as { doc: { id: string } }).doc.id
}

test.describe('accessibility', () => {
  test('the canvas shell', async ({ page, request }) => {
    const doc = await shell(page, request)
    try {
      await audit(page, 'canvas shell')
    } finally {
      await deleteWorkflow(request, doc.id)
    }
  })

  test('the node library, searched', async ({ page, request }) => {
    const doc = await shell(page, request)
    try {
      // The library is the sidebar's default panel; clicking its toolbar button would close it.
      await expect(page.getByTestId('node-library')).toBeVisible()
      await page.getByTestId('library-search').fill('spec')
      await expect(page.locator('[data-node-type]').first()).toBeVisible()
      await audit(page, 'node library', '[data-testid="node-library"]')
    } finally {
      await deleteWorkflow(request, doc.id)
    }
  })

  test('the inspector on a selected node, where AutoForm renders the widgets', async ({
    page,
    request,
  }) => {
    const doc = await shell(page, request)
    try {
      await page.getByTestId('node-sum').click()
      await expect(page.getByTestId('inspector')).toBeVisible()
      await audit(page, 'inspector', '[data-testid="inspector"]')
    } finally {
      await deleteWorkflow(request, doc.id)
    }
  })

  test('the command palette and the bottom drawer', async ({ page, request }) => {
    const doc = await shell(page, request)
    try {
      await page.getByTestId('toggle-drawer').click()
      await expect(page.getByTestId('drawer')).toBeVisible()
      await audit(page, 'bottom drawer', '[data-testid="drawer"]')

      await page.getByTestId('canvas').click({ position: { x: 30, y: 30 } })
      await page.keyboard.press('Control+K')
      await expect(page.getByTestId('palette')).toBeVisible()
      await audit(page, 'command palette', '[data-testid="palette"]')
    } finally {
      await deleteWorkflow(request, doc.id)
    }
  })

  test('the workspace and workflows panels', async ({ page, request }) => {
    const doc = await shell(page, request)
    try {
      await page.getByTestId('toggle-workspace').click()
      await expect(page.getByTestId('workspace-panel')).toBeVisible()
      await expect(page.getByTestId('workspace-root')).not.toBeEmpty()
      await audit(page, 'workspace panel', '[data-testid="workspace-panel"]')

      await page.getByTestId('toggle-workflows').click()
      await expect(page.getByTestId('workflows-panel')).toBeVisible()
      await audit(page, 'workflows panel', '[data-testid="workflows-panel"]')
    } finally {
      await deleteWorkflow(request, doc.id)
    }
  })

  test('the templates gallery', async ({ page }) => {
    await page.goto('/templates')
    await expect(page.getByTestId('gallery-list')).toBeVisible()
    await audit(page, 'templates gallery')
  })

  test('the four app-mode layouts of a real template', async ({ page, request }) => {
    test.slow()
    const id = await instantiate(request, ABSORPTION)
    try {
      for (const mode of ['app', 'wizard', 'dashboard', 'batch'] as const) {
        await page.goto(`/w/${encodeURIComponent(id)}/${mode}`)
        await expect(page.getByTestId(`${mode}-mode`)).toBeVisible({ timeout: 60000 })
        await audit(page, `${mode} mode`)
      }
    } finally {
      await deleteWorkflow(request, id)
    }
  })

  test('an expandable editor and the viewer sheet', async ({ page, request }) => {
    test.slow()
    const id = await instantiate(request, ABSORPTION)
    try {
      await openWorkflow(page, id)
      const continuum = page.locator('[data-testid="node-continuum"]')
      await expect(continuum.getByTestId('status-badge')).toHaveText(/done/i, { timeout: 90000 })

      await continuum.getByTestId('node-editor').click()
      const editor = page.getByTestId('editor')
      await expect(editor).toBeVisible()
      await audit(page, 'continuum editor', '[data-testid="editor"]')
      await page.getByTestId('editor-close').click()
      await expect(editor).toHaveCount(0)

      await page.locator('[data-testid="node-slice"]').getByTestId('preview-expand').click()
      await expect(page.getByTestId('viewer')).toBeVisible()
      await audit(page, 'viewer sheet', '[data-testid="viewer"]')
    } finally {
      await deleteWorkflow(request, id)
    }
  })
})
