/**
 * Phase 10 acceptance: the Redshift Finder template opens into its Dashboard, and dragging a
 * range on the chi-square curve highlights the matching rows of the candidates table — the two
 * views share the spectrum upstream, which is what links them.
 */
import { type APIRequestContext, type Page, expect, test } from '@playwright/test'

import { deleteWorkflow } from './helpers'
import { E2E_TOKEN } from '../playwright.config'

const TEMPLATE_ID = 'rbcodes.redshift-finder'

interface Saved {
  doc: { id: string }
  node_errors: Record<string, unknown[]>
  layout_errors: unknown[]
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

async function openDashboard(page: Page, id: string): Promise<void> {
  await page.goto(`/w/${encodeURIComponent(id)}/dashboard?token=${E2E_TOKEN}`)
  await expect(page.getByTestId('dashboard-mode')).toBeVisible()
  await page.getByTestId('ws-status').and(page.locator('[data-status="open"]')).waitFor()
  // Tiles appear once the document is open; the mode renders an empty state before that.
  await expect(page.getByTestId('dashboard-tile-view:curve')).toBeVisible()
}

/** Drag from `from` to `to` (fractions of the width) across a tile's selection layer. */
async function dragRange(page: Page, viewId: string, from: number, to: number): Promise<void> {
  const layer = page.getByTestId(`view-select-${viewId}`)
  await expect(layer).toBeVisible({ timeout: 60000 })
  const box = await layer.boundingBox()
  if (!box) throw new Error(`no box for ${viewId}`)
  const y = box.y + box.height / 2
  await page.mouse.move(box.x + box.width * from, y)
  await page.mouse.down()
  await page.mouse.move(box.x + box.width * to, y, { steps: 8 })
  await page.mouse.up()
}

test.describe('dashboard mode over the redshift template', () => {
  test('opens into the dashboard and links a curve selection to the candidates table', async ({
    page,
    request,
  }) => {
    const saved = await instantiate(request, 'E2E dashboard')
    const id = saved.doc.id
    expect(saved.layout_errors).toEqual([])
    try {
      await openDashboard(page, id)
      // The template's own tiles, in the layout it ships.
      await expect(page.getByTestId('dashboard-tile-view:curve')).toBeVisible()
      await expect(page.getByTestId('dashboard-tile-view:candidates')).toBeVisible()
      await expect(page.getByTestId('dashboard-tile-view:spectrum')).toBeVisible()

      // Wait for the search to finish so the tiles carry real data.
      await expect(page.getByTestId('view-tile-candidates')).toHaveAttribute('data-state', 'done', {
        timeout: 120000,
      })
      await expect(page.getByTestId('view-tile-curve')).toHaveAttribute('data-state', 'done', {
        timeout: 120000,
      })

      // Drag most of the chi-square curve: every candidate inside it lights up.
      await dragRange(page, 'curve', 0.05, 0.95)
      await expect(page.getByTestId('dashboard-selection')).toBeVisible()
      const table = page.getByTestId('view-tile-candidates')
      await expect(table).toHaveAttribute('data-linked', 'true')
      const highlighted = table.locator('tr[data-linked="true"]')
      await expect(highlighted.first()).toBeVisible()
      const wide = await highlighted.count()
      expect(wide).toBeGreaterThan(0)

      // A narrow range at the far left keeps fewer rows (or none): the link really filters.
      await dragRange(page, 'curve', 0.01, 0.03)
      await expect
        .poll(async () => Number(await table.getAttribute('data-selected-rows')))
        .toBeLessThan(wide)

      // Clearing the selection releases every tile.
      await page.getByTestId('dashboard-clear-selection').click()
      await expect(page.getByTestId('dashboard-selection')).toHaveCount(0)
      await expect(table).not.toHaveAttribute('data-linked', 'true')
    } finally {
      await deleteWorkflow(request, id)
    }
  })

  test('unlocks the grid, removes a tile and persists the layout', async ({ page, request }) => {
    const saved = await instantiate(request, 'E2E dashboard edit')
    const id = saved.doc.id
    try {
      await openDashboard(page, id)
      await page.getByTestId('dashboard-edit').click()
      await page.getByTestId('dashboard-remove-view:spectrum').click()
      await expect(page.getByTestId('dashboard-tile-view:spectrum')).toHaveCount(0)
      await page.getByTestId('dashboard-save-layout').click()

      await expect
        .poll(
          async () => {
            const doc = (await (
              await request.get(`/api/workflows/${encodeURIComponent(id)}`)
            ).json()) as { layouts: { dashboard: { items: { ref: string }[] } } }
            return doc.layouts.dashboard.items.map((tile) => tile.ref)
          },
          { timeout: 15000 },
        )
        .not.toContain('view:spectrum')

      // Undo puts it back, like any other document edit.
      await page.keyboard.press('Control+z')
      await expect(page.getByTestId('dashboard-tile-view:spectrum')).toBeVisible()
    } finally {
      await deleteWorkflow(request, id)
    }
  })

  test('the templates gallery opens each template into its default layout', async ({
    page,
    request,
  }) => {
    await page.goto(`/templates?token=${E2E_TOKEN}`)
    await expect(page.getByTestId('templates-gallery')).toBeVisible()
    const cards = page.locator('[data-testid^="gallery-card-"]')
    await expect(cards).toHaveCount(4)
    await expect(
      page.getByTestId('gallery-card-rbcodes.absorption-line-measurement'),
    ).toHaveAttribute('data-layout', 'wizard')
    await expect(page.getByTestId('gallery-card-rbcodes.redshift-finder')).toHaveAttribute(
      'data-layout',
      'dashboard',
    )

    await page.getByTestId('gallery-open-rbcodes.redshift-finder').click()
    await expect(page.getByTestId('dashboard-mode')).toBeVisible({ timeout: 30000 })
    await expect(page).toHaveURL(/\/w\/[^/]+\/dashboard$/)

    await deleteWorkflow(request, page.url().split('/w/')[1]?.split('/')[0] ?? 'none')
  })
})
