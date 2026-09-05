/**
 * Keyboard and motion (phase 13, scope item 3).
 *
 * Three things axe cannot check for you:
 *
 * 1. **The absorption wizard completes with the keyboard alone** — Tab to reach a control, Enter
 *    to use it, nothing else. This is the tier a lab user is most likely to be handed, and a
 *    wizard whose Next button is unreachable is unusable however clean its markup is.
 * 2. **Every control the Tab order reaches shows where the focus is.** `outline-none` plus a
 *    `focus-visible:ring` is the house style, and one control that forgets the ring is invisible
 *    to a keyboard user.
 * 3. **`prefers-reduced-motion` is honoured**, which is a stylesheet rule and therefore exactly
 *    the kind of thing that gets silently dropped.
 */
import type { APIRequestContext, Page } from '@playwright/test'
import { E2E_TOKEN, expect, test } from './fixtures'

import { createWorkflow, deleteWorkflow, mathChain, openWorkflow, uniqueId } from './helpers'

const TEMPLATE_ID = 'rbcodes.absorption-line-measurement'

/** What is focused right now: its test id, tag and whether it shows a focus indicator. */
async function focused(page: Page): Promise<{ id: string; tag: string; ring: boolean }> {
  return page.evaluate(() => {
    const el = document.activeElement as HTMLElement | null
    if (!el) return { id: '', tag: '', ring: false }
    const style = getComputedStyle(el)
    const outline =
      style.outlineStyle !== 'none' && Number.parseFloat(style.outlineWidth || '0') > 0
    const shadow = style.boxShadow !== 'none' && style.boxShadow !== ''
    return {
      id: el.dataset.testid ?? el.getAttribute('aria-label') ?? '',
      tag: el.tagName.toLowerCase(),
      ring: outline || shadow,
    }
  })
}

/** Tab until `testId` has the focus, then leave it focused. Fails if it is unreachable. */
async function tabTo(page: Page, testId: string, limit = 60): Promise<void> {
  for (let i = 0; i < limit; i += 1) {
    if ((await focused(page)).id === testId) return
    await page.keyboard.press('Tab')
  }
  const where = await focused(page)
  throw new Error(`"${testId}" was not reachable within ${limit} tabs (stopped on ${where.id})`)
}

/**
 * Every node's state and error, for a failure message. A wizard shows one step at a time, so a
 * failure inside it says nothing about which node is unhappy -- and this one ran four nightlies
 * on a runner nobody here has.
 */
async function nodeStates(request: APIRequestContext, id: string): Promise<string> {
  try {
    const body = (await (
      await request.get(`/api/workflows/${encodeURIComponent(id)}/status`)
    ).json()) as { nodes: Record<string, { state: string; error: string | null }> }
    return Object.entries(body.nodes)
      .map(([node, n]) => `${node}=${n.state}${n.error ? ` (${n.error})` : ''}`)
      .join(', ')
  } catch (error) {
    return `unavailable: ${String(error)}`
  }
}

test.describe('keyboard and motion', () => {
  test('the absorption wizard completes with the keyboard alone', async ({ page, request }) => {
    test.slow()
    const response = await request.post(
      `/api/templates/${encodeURIComponent(TEMPLATE_ID)}/instantiate`,
      { data: { name: `keyboard ${uniqueId('w')}` } },
    )
    expect(response.status()).toBe(201)
    const id = ((await response.json()) as { doc: { id: string } }).doc.id
    try {
      await page.goto(`/w/${encodeURIComponent(id)}/wizard?token=${E2E_TOKEN}`)
      await expect(page.getByTestId('wizard-mode')).toBeVisible()
      await expect(page.getByTestId('wizard-step-0')).toBeVisible()

      /** A step is ready when its own node has finished. */
      const settled = async (index: number): Promise<void> => {
        await expect(page.getByTestId(`wizard-step-${index}`)).toHaveAttribute(
          'data-state',
          'done',
          { timeout: 90000 },
        )
      }

      // Steps 1 to 5: wait for the step's own node, then Tab to Next and press it.
      for (let index = 0; index < 5; index += 1) {
        await settled(index)
        if (index === 1) {
          // The redshift step: reach the field and retype it without touching the mouse.
          const field = page.getByTestId('wizard-body-1').locator('input').first()
          await field.focus()
          await page.keyboard.press('Control+A')
          await page.keyboard.type('1.3855')
          await page.keyboard.press('Enter')
          // Committing the field is an edit: wait for the step to come back before advancing,
          // so a failure here is about the step and not about the edit still being in flight.
          await settled(index)
        }
        await tabTo(page, 'wizard-next')
        await page.keyboard.press('Enter')
        await expect(page.getByTestId(`wizard-body-${index + 1}`)).toBeVisible()
      }

      // The last step offers the export instead of Next. Press it the moment it is reachable,
      // exactly as a user does: waiting for the values the export writes is the server's job
      // (`Scheduler.settle`), and this is the test that caught two client-side attempts at it.
      await expect(page.getByTestId('wizard-next')).toHaveCount(0)
      await tabTo(page, 'wizard-export')
      await page.keyboard.press('Enter')
      // Either the export lands or something went wrong and said so in a toast; waiting only for
      // the happy path turns a real failure into "element not found" 60 seconds later.
      const exported = page.getByTestId('wizard-exported')
      await expect(exported.or(page.getByTestId('toast')).first()).toBeVisible({ timeout: 120000 })
      const toast = await page
        .getByTestId('toast')
        .textContent()
        .catch(() => null)
      await expect(
        exported,
        `export failed; the toast said: ${toast ?? '(nothing)'}; nodes: ${await nodeStates(request, id)}`,
      ).toContainText('exports/', { timeout: 30000 })
    } finally {
      await deleteWorkflow(request, id)
    }
  })

  test('every control the Tab order reaches shows where the focus is', async ({
    page,
    request,
  }) => {
    const doc = mathChain()
    await createWorkflow(request, doc)
    try {
      await openWorkflow(page, doc.id)
      await expect(page.getByTestId('run')).toBeEnabled()
      await page.locator('body').click({ position: { x: 2, y: 2 } })

      const seen: string[] = []
      const unmarked: string[] = []
      for (let i = 0; i < 40; i += 1) {
        await page.keyboard.press('Tab')
        const where = await focused(page)
        if (where.tag === 'body' || seen.includes(`${where.tag}:${where.id}`)) continue
        seen.push(`${where.tag}:${where.id}`)
        if (!where.ring) unmarked.push(`${where.tag} ${where.id || '(unlabelled)'}`)
      }
      expect(seen.length, 'the Tab order reached some controls').toBeGreaterThan(8)
      expect(unmarked, 'controls with no visible focus indicator').toEqual([])
    } finally {
      await deleteWorkflow(request, doc.id)
    }
  })

  test('prefers-reduced-motion stops the transitions', async ({ page, request }) => {
    const doc = mathChain()
    await createWorkflow(request, doc)
    try {
      await openWorkflow(page, doc.id)
      const durations = async (): Promise<{ transition: string; animation: string }> =>
        page.evaluate(() => {
          const button = document.querySelector('[data-testid="run"]')!
          const style = getComputedStyle(button)
          return { transition: style.transitionDuration, animation: style.animationDuration }
        })

      const normal = await durations()
      expect(Number.parseFloat(normal.transition)).toBeGreaterThan(0)

      await page.emulateMedia({ reducedMotion: 'reduce' })
      const reduced = await durations()
      expect(Number.parseFloat(reduced.transition)).toBeLessThan(0.01)
    } finally {
      await deleteWorkflow(request, doc.id)
    }
  })
})
