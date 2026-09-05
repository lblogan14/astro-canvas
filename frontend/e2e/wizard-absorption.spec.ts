/**
 * Phase 10 acceptance: the absorption template's Wizard completes a measurement without ever
 * showing the canvas — the steps gate on their own nodes, going back preserves what was typed,
 * and the results step exports the outputs into the workspace.
 */
import type { APIRequestContext, Page } from '@playwright/test'
import { E2E_TOKEN, expect, test } from './fixtures'

import { deleteWorkflow } from './helpers'

const TEMPLATE_ID = 'rbcodes.absorption-line-measurement'

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

/** Open straight into the Wizard through the URL, as the gallery's Open button does. */
async function openWizard(page: Page, id: string): Promise<void> {
  await page.goto(`/w/${encodeURIComponent(id)}/wizard?token=${E2E_TOKEN}`)
  await expect(page.getByTestId('wizard-mode')).toBeVisible()
  await page.getByTestId('ws-status').and(page.locator('[data-status="open"]')).waitFor()
  // The steps appear once the document is open; the mode renders an empty state before that.
  await expect(page.getByTestId('wizard-step-0')).toBeVisible()
}

function step(page: Page, index: number) {
  return page.getByTestId(`wizard-step-${index}`)
}

/** Wait for a step to be ready, then move on. */
async function advance(page: Page, index: number): Promise<void> {
  await expect(step(page, index)).toHaveAttribute('data-state', 'done', { timeout: 60000 })
  await page.getByTestId('wizard-next').click()
  await expect(page.getByTestId(`wizard-body-${index + 1}`)).toBeVisible()
}

test.describe('wizard mode over the absorption template', () => {
  test('walks Load to Save without the canvas and keeps values across steps', async ({
    page,
    request,
  }) => {
    const saved = await instantiate(request, 'E2E wizard')
    const id = saved.doc.id
    expect(saved.node_errors).toEqual({})
    expect(saved.layout_errors).toEqual([])
    try {
      await openWizard(page, id)
      // The graph is never rendered in this mode.
      await expect(page.getByTestId('canvas')).toHaveCount(0)

      const titles = await page.getByTestId('wizard-stepper').locator('button').allInnerTexts()
      expect(titles.slice(0, 6).map((t) => t.trim())).toEqual([
        'Load',
        'Redshift',
        'Transition',
        'Continuum',
        'Measure',
        'Save',
      ])

      // Step 1: the bundled spectrum is already loaded, so Next opens as soon as it has run.
      await advance(page, 0)

      // Step 2: change the redshift, then put it back — the field keeps what was typed.
      const redshift = page.getByTestId('wizard-body-1').locator('input').first()
      await expect(redshift).toHaveValue('1.3855')
      await redshift.fill('1.4')
      await redshift.blur()
      await advance(page, 1)
      await page.getByTestId('wizard-back').click()
      await expect(page.getByTestId('wizard-body-1').locator('input').first()).toHaveValue('1.4')
      await page.getByTestId('wizard-body-1').locator('input').first().fill('1.3855')
      await page.getByTestId('wizard-body-1').locator('input').first().blur()
      await advance(page, 1)

      // Steps 3 to 5: transition, continuum and the measurement itself.
      await advance(page, 2)
      await advance(page, 3)
      await expect(step(page, 4)).toHaveAttribute('data-state', 'done', { timeout: 60000 })

      // The measurement is on screen as a view tile, without ever opening the canvas.
      const measurement = page.getByTestId('wizard-views').first()
      await expect(measurement).toContainText(/W/, { timeout: 30000 })
      await page.getByTestId('wizard-next').click()

      // Step 6 is the last one: it offers the export instead of Next.
      await expect(page.getByTestId('wizard-body-5')).toBeVisible()
      await expect(page.getByTestId('wizard-next')).toHaveCount(0)
      await page.getByTestId('wizard-export').click()
      await expect(page.getByTestId('wizard-exported')).toContainText('exports/', {
        timeout: 30000,
      })

      // The exported file is really in the workspace.
      const dir = (await page.getByTestId('wizard-exported').textContent()) ?? ''
      const folder = dir.replace(/^.*?(exports\/[^\s]+).*$/s, '$1')
      const listed = await request.get(`/api/workspace/tree?path=${encodeURIComponent(folder)}`)
      expect(listed.ok()).toBe(true)
      const body = (await listed.json()) as { entries: { name: string }[] }
      expect(body.entries.some((entry) => entry.name.startsWith('ew.out'))).toBe(true)
    } finally {
      await deleteWorkflow(request, id)
    }
  })

  test('skips to the results and returns to the graph on demand', async ({ page, request }) => {
    const saved = await instantiate(request, 'E2E wizard skip')
    const id = saved.doc.id
    try {
      await openWizard(page, id)
      await page.getByTestId('wizard-skip').click()
      await expect(page.getByTestId('wizard-body-5')).toBeVisible()

      await page.getByTestId('wizard-show-graph').click()
      await expect(page.getByTestId('canvas')).toBeVisible()
      await expect(page).toHaveURL(new RegExp(`/w/${id}$`))
    } finally {
      await deleteWorkflow(request, id)
    }
  })

  test('the step editor moves a parameter and saves the layout', async ({ page, request }) => {
    const saved = await instantiate(request, 'E2E wizard editor')
    const id = saved.doc.id
    try {
      await openWizard(page, id)
      await page.getByTestId('wizard-edit').click()
      await expect(page.getByTestId('wizard-editor')).toBeVisible()

      // Move "Absorber z" from the Redshift step into the Load step.
      const item = page.getByTestId('wizard-item-promoted:redshift.z')
      await item.getByRole('button').first().click()
      await page.getByTestId('wizard-save-layout').click()
      await expect(page.getByTestId('wizard-editor')).toHaveCount(0)

      // The document autosaves about a second after the edit.
      await expect
        .poll(
          async () => {
            const doc = (await (
              await request.get(`/api/workflows/${encodeURIComponent(id)}`)
            ).json()) as {
              layouts: { wizard: { steps: { title: string; items: string[] }[] } }
            }
            return doc.layouts.wizard.steps[0]?.items
          },
          { timeout: 15000 },
        )
        .toEqual(['promoted:load.path', 'promoted:redshift.z'])
    } finally {
      await deleteWorkflow(request, id)
    }
  })
})
